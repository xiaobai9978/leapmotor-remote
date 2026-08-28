# -*- coding: utf-8 -*-
# 零跑智控验证码登录链路（服务器端自动登录，替代抓包）
# 流程：RSA加密手机号 → sendmessagecode(发验证码) → check_login_with_phone(验证码登录)
#       → account/v1/login(换正式凭证 accessToken/signKeyBase64)
import base64
import hashlib
import hmac
import random
import time
import requests
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ===== RSA-1024 公钥（智控 App Crypto.DEFAULT_PUBLIC_KEY，公开信息）=====
PUB_KEY_B64 = 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDHUIQKhkwNqJFTZPe98mC1lmpbY9r/+7PEWZg8ebqYXT3sumKRaQ0zcoTx42x0iybmCRXy4CcZrgGAbwKzwqwNw0rFquJ6c7mgQA6k3lZU3p96qBlzK7DSkoFR6mO9pjcd2hlJ8wH+IwI5b8IWWZhwVN/4cM7npG0S0zeRn3soEwIDAQAB'
VERSION = '1.22.87'


def _parse_rsa_pubkey():
    """解析 SPKI DER 公钥，返回 (n, e)（正确处理长格式长度）"""
    der = base64.b64decode(PUB_KEY_B64)
    idx = der.index(b'\x02')
    len_byte = der[idx + 1]
    if len_byte & 0x80:
        num_len = len_byte & 0x7f
        n_len = int.from_bytes(der[idx + 2:idx + 2 + num_len], 'big')
        n_start = idx + 2 + num_len
    else:
        n_len = len_byte
        n_start = idx + 2
    n = int.from_bytes(der[n_start:n_start + n_len], 'big')
    e_idx = n_start + n_len
    e_len_byte = der[e_idx + 1]
    if e_len_byte & 0x80:
        num_len = e_len_byte & 0x7f
        e_len = int.from_bytes(der[e_idx + 2:e_idx + 2 + num_len], 'big')
        e_start = e_idx + 2 + num_len
    else:
        e_len = e_len_byte
        e_start = e_idx + 2
    e = int.from_bytes(der[e_start:e_start + e_len], 'big')
    return n, e


def rsa_encrypt_phone(phone):
    """RSA-1024 PKCS1 v1.5 加密手机号 → base64url"""
    n, e = _parse_rsa_pubkey()
    msg = phone.encode('utf-8')
    k = (n.bit_length() + 7) // 8  # 128
    ps_len = k - 3 - len(msg)
    ps = bytes([random.randint(1, 255) for _ in range(ps_len)])
    em = b'\x00\x02' + ps + b'\x00' + msg
    m_int = int.from_bytes(em, 'big')
    c_int = pow(m_int, e, n)
    ct = c_int.to_bytes(k, 'big')
    return base64.urlsafe_b64encode(ct).decode()


def _old_headers(device_id):
    return {
        'APPPlatform': 'Android',
        'APPVersion': VERSION,
        'APPImei': device_id,
        'C-VERSIONS': 'APP',
        'XFX-CDN-VRS': 'v4',
        'User-Agent': 'okhttp/4.12.0',
        'Accept-Encoding': 'gzip',
    }


def send_sms(phone, device_id):
    """发送验证码。返回 (成功, 信息)"""
    ct = rsa_encrypt_phone(phone)
    url = 'https://appuser.leapmotor.cn/app-user/applogin/compliance/sendmessagecode?phoneNo=' + ct
    r = requests.get(url, headers=_old_headers(device_id), timeout=20)
    d = r.json()
    if d.get('code') == 200 or d.get('success'):
        return True, '验证码已发送'
    return False, str(d)[:100]


def login_with_sms(phone, sms_code, device_id):
    """验证码登录。返回 (成功, token, refreshToken, accountId)"""
    ct = rsa_encrypt_phone(phone)
    url = ('https://appuser.leapmotor.cn/app-user/applogin/check_login_with_phone?'
           'phoneNoCiphertext=' + ct +
           '&smsCode=' + sms_code +
           '&deviceID=' + device_id +
           '&smDeviceId=' + device_id +
           '&os=android&pageUrl=')
    r = requests.post(url, headers=_old_headers(device_id), timeout=20)
    d = r.json()
    if d.get('code') == 200 and d.get('success'):
        vo = d.get('data', {}).get('appLoginVO', {})
        return True, vo.get('token', ''), vo.get('refreshToken', ''), vo.get('accountId', '')
    return False, '', '', ''


def _new_headers(device_id, nonce, ts, body_str, sign_key):
    """通用 API 签名头（排序拼接 + HMAC-SHA256）"""
    fields = {
        'acceptLanguage': 'zh-CN',
        'channel': '1',
        'deviceId': device_id,
        'deviceType': 'android',
        'nonce': nonce,
        'source': 'leapmotor',
        'timestamp': ts,
        'version': VERSION,
    }
    import json as _json
    try:
        bd = _json.loads(body_str)
        for k, v in bd.items():
            fields[k] = str(v)
    except Exception:
        pass
    vs = ''.join(str(v) for k, v in sorted(fields.items()))
    sign = hmac.new(sign_key, vs.encode('utf-8'), hashlib.sha256).hexdigest()
    return {
        'source': 'leapmotor',
        'channel': '1',
        'acceptLanguage': 'zh-CN',
        'x-region': 'CN',
        'x-api-signature-version': '2.0',
        'version': VERSION,
        'deviceType': 'android',
        'nonce': nonce,
        'timestamp': ts,
        'deviceId': device_id,
        'x-subversion': '3.19.2-2',
        'sign': sign,
        'Content-Type': 'application/json; charset=utf-8',
        'User-Agent': 'okhttp/4.12.0',
    }


if __name__ == '__main__':
    phone = sys.argv[1] if len(sys.argv) > 1 else ''
    if not phone:
        print('用法: python login_leapmotor.py 手机号 [验证码] [deviceID]')
        sys.exit(0)
    device_id = sys.argv[3] if len(sys.argv) > 3 else ''
    if len(sys.argv) > 2:
        ok, token, rt, aid = login_with_sms(phone, sys.argv[2], device_id)
        print('登录:', 'OK' if ok else 'FAIL', 'accountId=' + aid)
        if ok:
            print('token=' + token)
            print('refreshToken=' + rt)
    else:
        ok, info = send_sms(phone, device_id)
        print('发送验证码:', 'OK' if ok else 'FAIL', info)
