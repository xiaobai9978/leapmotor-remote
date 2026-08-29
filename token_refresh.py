# -*- coding: utf-8 -*-
# 零跑车控凭证自动刷新模块
# getnewtoken 接口已破解：signStr = md5Short(accountId+accountNumber+deviceID+nonce+refreshToken+timespan)
# 凭证失效时调用 refresh_token() 自动换新 token（约 6 小时过期，可无限续）
# 刷新凭证参数从 config.py 读取（ACCOUNT_ID / ACCOUNT_NUMBER / REFRESH_TOKEN / DEVICE_ID）
import hashlib
import time
import random
import requests

try:
    import config
except ImportError:
    raise SystemExit('缺少 config.py！请复制 config.example.py 为 config.py 并填写真实凭证')

ACCOUNT_ID = config.ACCOUNT_ID
ACCOUNT_NUMBER = config.ACCOUNT_NUMBER
REFRESH_TOKEN = config.REFRESH_TOKEN
DEVICE_ID = config.DEVICE_ID
VERSION = getattr(config, 'VERSION', '1.22.87')


def md5_short(s):
    """signStr 统一算法：MD5 取中间 16 位"""
    return hashlib.md5(s.encode('utf-8')).hexdigest()[8:24]


def refresh_token():
    """调用 getnewtoken 换新 token。返回 (成功, 新token, 信息)"""
    timespan = str(int(time.time() * 1000))
    nonce = str(random.randint(100000, 9999999))
    signstr = md5_short(ACCOUNT_ID + ACCOUNT_NUMBER + DEVICE_ID + nonce + REFRESH_TOKEN + timespan)
    url = ('https://appuser.leapmotor.cn/app-user/appuseroperate/getnewtoken?'
           'timespan=' + timespan + '&nonce=' + nonce +
           '&deviceID=' + DEVICE_ID +
           '&accountId=' + ACCOUNT_ID +
           '&accountNumber=' + ACCOUNT_NUMBER +
           '&signStr=' + signstr)
    headers = {
        'APPPlatform': 'Android',
        'APPVersion': VERSION,
        'APPImei': DEVICE_ID,
        'C-VERSIONS': 'APP',
        'XFX-CDN-VRS': 'v4',
        'XFX-CDN-CROSS-NODE': config.TOKEN,
        'XFX-CDN-CROSS-REFRESH-NODE': REFRESH_TOKEN,
        'User-Agent': 'okhttp/4.12.0',
        'Accept-Encoding': 'gzip',
    }
    try:
        r = requests.get(url, headers=headers, timeout=20)
        d = r.json()
        if d.get('code') == 200 and d.get('success'):
            token = d.get('data', {}).get('token', '')
            return True, token, '刷新成功'
        return False, '', str(d)[:100]
    except Exception as e:
        return False, '', '网络异常: ' + str(e)


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ok, token, info = refresh_token()
    print('刷新:', 'OK' if ok else 'FAIL', info)
    if ok:
        print('新TOKEN=' + token)
        print('有效期约6小时，写入 config.py 的 TOKEN 即可（车控失败会自动刷新）')
