# -*- coding: utf-8 -*-
# 零跑车控核心库：解锁/上锁/状态查询（配置从 config.py 读取）
# signStr = MD5(carvin + cmdid + deviceID + nonce + oppwd + '\n' + state + timespan + token)[8:24]
import hashlib
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


def send_control(action):
    """解锁/上锁。action: unlock / lock。返回 (成功, msgID, 信息)"""
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
        return False, '', data.get('message', '失败 code=' + str(data.get('code')))
    except Exception as e:
        return False, '', '网络异常: ' + str(e)


def get_vehicle_status():
    """查询车辆门锁状态（信号查询接口）。返回 (锁定?, 数据)"""
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


if __name__ == '__main__':
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else 'unlock'
    ok, msg_id, info = send_control(action)
    print(action, '->', 'OK' if ok else 'FAIL', info, 'msgID=' + msg_id)
