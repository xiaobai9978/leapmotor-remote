# -*- coding: utf-8 -*-
# ===== 零跑车控配置文件 =====
# 使用方法：复制本文件为 config.py，填入真实值（config.py 已被 .gitignore 忽略，不会提交到 git）

# 车辆识别码（VIN）
CARVIN = 'YOUR_CARVIN'

# 设备 ID（智控 App 生成的设备标识）
DEVICE_ID = 'YOUR_DEVICE_ID'

# 操作密码加密值（智控 App 设置操作密码后生成，抓取方式见 README）
OPPWD = 'YOUR_OPPWD'

# 登录令牌（智控 App 登录后获取，XFX-CDN-CROSS-NODE 请求头值）
TOKEN = 'YOUR_TOKEN'

# 通用 API 签名密钥（登录响应 signKeyBase64，base64 格式）
SIGN_KEY_B64 = 'YOUR_SIGN_KEY_BASE64'

# 新协议 JWT accessToken（通用 API 请求头 token）
ACCESS_TOKEN = 'YOUR_ACCESS_TOKEN'

# 账号 ID
USER_ID = 'YOUR_USER_ID'

# 车控服务安全密钥（快捷指令 URL 携带）
API_KEY = 'YOUR_API_KEY'

# App 版本标识
VERSION = '1.22.87'

# 车型
CAR_TYPE = 'T03'
