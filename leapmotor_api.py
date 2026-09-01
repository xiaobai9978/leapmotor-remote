# -*- coding: utf-8 -*-
# 零跑车控核心库：解锁/上锁/状态查询（配置从 config.py 读取）
# signStr = MD5(carvin + cmdid + deviceID + nonce + oppwd + '\n' + state + timespan + token)[8:24]
import hashlib
import sys
import time
import random
import base64
import hmac
import requests

try:
    import config
except ImportError:
    raise SystemExit('缺少 config.py！请复制 config.example.py 为 config.py 并填写真实凭证')

CARVIN = config.CARVIN
DEVICE_ID = config.DEVICE_ID
OPPWD = config.OPPWD
TOKEN = config.TOKEN
SIGN_KEY_B64 = config.SIGN_KEY_B64
ACCESS_TOKEN = config.ACCESS_TOKEN
USER_ID = config.USER_ID
VERSION = getattr(config, 'VERSION', '1.22.87')
CAR_TYPE = getattr(config, 'CAR_TYPE', 'T03')

_GATEWAY = 'https://appgateway.leapmotor.com'

# 并发刷新互斥锁（RLock 可重入：send_control 外层加锁后内部 _refresh_token_inner 再加锁不卡死）
import threading
_refresh_lock = threading.RLock()


def _is_64hex(s):
    """token 格式自检：必须是 64 位十六进制，否则拒绝写入（防污染好凭证）"""
    return isinstance(s, str) and len(s) == 64 and all(c in '0123456789abcdefABCDEF' for c in s)

# 凭证自动刷新（getnewtoken 换新 token + oppwd 自动重算）
import token_refresh


def gen_oppwd(token, pwd='9978'):
    """oppwd = base64(AES-CBC(key=md5(token_half)[8:24], iv=md5(token_half)[8:24], pwd))"""
    import base64 as _b64
    try:
        from Crypto.Cipher import AES
    except ImportError:
        # 无 pycryptodome 时用内置回退（服务器需 pip install pycryptodome）
        raise RuntimeError('需要 pycryptodome：pip install pycryptodome')
    kv = hashlib.md5(token[:32].encode()).hexdigest()[8:24].encode()
    pad = 16 - (len(pwd) % 16)
    plain = pwd.encode() + bytes([pad]) * pad
    cipher = AES.new(kv, AES.MODE_CBC, kv)
    return _b64.b64encode(cipher.encrypt(plain)).decode()


def _refresh_token_inner(update_legacy=True):
    """getnewtoken 换新凭证（锁内串行，防并发互踢）。
    update_legacy=True：旧协议 token/oppwd 也同步（并写回 config）；
    update_legacy=False：只更新新协议 ACCESS_TOKEN（不碰旧协议凭证，防污染）。
    成功返回 (True, 说明)，失败返回 (False, 原因)。"""
    global TOKEN, OPPWD, ACCESS_TOKEN
    with _refresh_lock:
        ok, new_token, info = token_refresh.refresh_token()
        if not (ok and new_token):
            return False, 'getnewtoken 失败: ' + str(info)[:60]
        if not _is_64hex(new_token):
            # token 格式异常：拒绝写入，保持原凭证（防把好凭证换坏）
            return False, '新 token 格式异常，拒绝写入（保持原凭证）'
        if update_legacy and new_token == TOKEN:
            return False, 'token 未变化'
        if not update_legacy:
            ACCESS_TOKEN = new_token
            return True, '已刷新 ACCESS_TOKEN（新协议）'
        TOKEN = new_token
        try:
            OPPWD = gen_oppwd(new_token)
        except Exception:
            return False, 'oppwd 重算失败: ' + str(sys.exc_info()[1])
        ACCESS_TOKEN = new_token  # 新协议（状态查询）与旧协议共用同一 token
        # 同步回 config（持久化，重启不丢）
        try:
            cfg_path = '/www/wwwroot/car/config.py'
            with open(cfg_path, 'r', encoding='utf-8') as f:
                content = f.read()
            import re
            content = re.sub(r"TOKEN = '.*?'", "TOKEN = '" + new_token + "'", content)
            content = re.sub(r"OPPWD = '.*?'", "OPPWD = '" + OPPWD + "'", content)
            content = re.sub(r"ACCESS_TOKEN = '.*?'", "ACCESS_TOKEN = '" + new_token + "'", content)
            with open(cfg_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception:
            pass
        return True, '已刷新并同步 config'


def _headers():
    return {
        'APPPlatform': 'Android',
        'APPVersion': VERSION,
        'APPImei': DEVICE_ID,
        'C-VERSIONS': 'APP',
        'XFX-CDN-VRS': 'v4',
        'XFX-CDN-CROSS-NODE': TOKEN,
        'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
        'User-Agent': 'okhttp/4.12.0',
        'Accept-Encoding': 'gzip',
    }


def _signstr(cmdid, nonce, state, timespan):
    vs = CARVIN + cmdid + DEVICE_ID + nonce + OPPWD + '\n' + state + timespan + TOKEN
    return hashlib.md5(vs.encode('utf-8')).hexdigest()[8:24]


_refreshed_at = 0.0  # 上次成功刷新凭证的时间（token 换出后约 60-90 秒才生效）


def _is_cred_error(m):
    """凭证类错误（可刷新/等待解决）判断；风控中不触发"""
    if '累计' in m or '3次' in m:
        return False
    return any(k in m for k in ('密码', '校验失败', 'TOKEN', '过期', '重新登录'))


def send_control(action):
    """解锁/上锁。凭证失效时自动刷新并重试（已证实 token 刷新后即时生效，无需长等待）。
    刷新失败（官方间歇/限流）时等 10 秒再试，最多三轮；仍失败返回错误由上层处理。
    返回 (成功, msgID, 信息)"""
    global _refreshed_at
    for _ in range(3):
        ok, mid, msg = _send_control(action)
        if ok:
            return True, mid, msg
        m = str(msg)
        if not _is_cred_error(m):
            return False, '', m
        # 刷新凭证（并发互斥；5 秒内刚刷过则直接用新凭证重试）
        with _refresh_lock:
            if time.time() - _refreshed_at > 5:
                ok_r, _ = _refresh_token_inner()
                if ok_r:
                    _refreshed_at = time.time()
        if time.time() - _refreshed_at > 5:
            # 刷新失败（间歇/限流）：等 10 秒再试一轮
            time.sleep(10)
    return False, '', m


def _send_control(action):
    """实际发送（用当前内存凭证），不含刷新逻辑"""
    cmdid = '110'
    state = '{"value":"' + action + '"}'
    timespan = str(int(time.time() * 1000))
    nonce = str(random.randint(100000, 9999999))
    signstr = _signstr(cmdid, nonce, state, timespan)
    body = ('timespan=' + timespan +
            '&nonce=' + nonce +
            '&deviceID=' + DEVICE_ID +
            '&cmdid=' + cmdid +
            '&state=' + requests.utils.quote(state, safe='') +
            '&carvin=' + CARVIN +
            '&oppwd=' + requests.utils.quote(OPPWD + '\n', safe='') +
            '&signStr=' + signstr)
    try:
        r = requests.post(_GATEWAY + '/app/app-control-service/v3/api/appremotectl',
                          headers=_headers(), data=body, timeout=20)
        data = r.json()
        if data.get('code') == 0 or data.get('result') == 0:
            return True, str(data.get('data', '')), data.get('message', '请求成功')
        msg = data.get('message', '失败 code=' + str(data.get('code')))
        return False, '', msg
    except Exception as e:
        return False, '', '网络异常: ' + str(e)


def _send_control_retry(action):
    """刷新凭证后的重试发送（兼容保留）"""
    cmdid = '110'
    state = '{"value":"' + action + '"}'
    timespan = str(int(time.time() * 1000))
    nonce = str(random.randint(100000, 9999999))
    signstr = _signstr(cmdid, nonce, state, timespan)
    body = ('timespan=' + timespan +
            '&nonce=' + nonce +
            '&deviceID=' + DEVICE_ID +
            '&cmdid=' + cmdid +
            '&state=' + requests.utils.quote(state, safe='') +
            '&carvin=' + CARVIN +
            '&oppwd=' + requests.utils.quote(OPPWD + '\n', safe='') +
            '&signStr=' + signstr)
    try:
        r = requests.post(_GATEWAY + '/app/app-control-service/v3/api/appremotectl',
                          headers=_headers(), data=body, timeout=20)
        data = r.json()
        if data.get('code') == 0 or data.get('result') == 0:
            return True, str(data.get('data', '')), data.get('message', '请求成功(已刷新凭证)')
        return False, '', data.get('message', '失败 code=' + str(data.get('code')))
    except Exception as e:
        return False, '', '网络异常: ' + str(e)


def _query_vehicle_status():
    """新协议门锁查询（实际请求，用当前 ACCESS_TOKEN）。返回 (锁定?, 原始响应)"""
    ts = str(int(time.time() * 1000))
    nonce = str(random.randint(100000, 9999999))
    fields = {
        'acceptLanguage': 'zh-CN',
        'channel': '1',
        'deviceId': DEVICE_ID,
        'deviceType': 'android',
        'nonce': nonce,
        'source': 'leapmotor',
        'timestamp': ts,
        'version': VERSION,
        'vin': CARVIN,
    }
    vs = ''.join(str(v) for k, v in sorted(fields.items()))
    sign_key = base64.b64decode(SIGN_KEY_B64)
    sign = hmac.new(sign_key, vs.encode('utf-8'), hashlib.sha256).hexdigest()

    headers = {
        'source': 'leapmotor',
        'channel': '1',
        'acceptLanguage': 'zh-CN',
        'x-region': 'CN',
        'x-api-signature-version': '2.0',
        'version': VERSION,
        'deviceType': 'android',
        'nonce': nonce,
        'timestamp': ts,
        'deviceId': DEVICE_ID,
        'userId': USER_ID,
        'carvin': CARVIN,
        'cartype': CAR_TYPE,
        'x-subversion': '3.19.2-2',
        'token': ACCESS_TOKEN,
        'sign': sign,
        'Content-Type': 'application/json; charset=utf-8',
        'User-Agent': 'okhttp/4.12.0',
    }
    try:
        r = requests.post(_GATEWAY + '/app/app-signal-service/signal/info/query',
                          headers=headers, json={'vin': CARVIN}, timeout=20)
        data = r.json()
        if data.get('code') == 0:
            sm = data.get('data', {}).get('signalMap', {})
            return sm.get('driverDoorLockStatus'), data
        return None, data
    except Exception as e:
        return None, {'error': str(e)}


def get_vehicle_status():
    """查询车辆门锁状态（凭证失效自动刷新重试一次）。返回 (锁定?, 数据)"""
    locked, data = _query_vehicle_status()
    if locked is not None:
        return locked, data
    msg = str(data.get('message', '')) if isinstance(data, dict) else str(data)
    # 新协议失败：仅刷新 ACCESS_TOKEN（不碰旧协议凭证，防污染）；"密码"类错误不触发
    if 'TOKEN' in msg or '过期' in msg or '登录' in msg:
        ok_refresh, _ = _refresh_token_inner(update_legacy=False)
        if ok_refresh:
            return _query_vehicle_status()
    return locked, data


if __name__ == '__main__':
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else 'unlock'
    ok, msg_id, info = send_control(action)
    print(action, '->', 'OK' if ok else 'FAIL', info, 'msgID=' + msg_id)
