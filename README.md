# 零跑车控远程控制（Leapmotor Remote Control）

通过逆向零跑官方车控协议，实现不依赖官方 App 的**远程解锁 / 上锁 / 状态查询**，并通过自建 HTTP 服务接入 **iPhone 快捷指令 / NFC 自动化**，实现"靠近自动解锁"。

> ⚠️ **仅供个人学习与自用**。逆向接口可能随 App 版本变化，请勿滥用。

## 功能

| 功能 | 说明 |
|------|------|
| 🔓 解锁 | 远程下发解锁指令 |
| 🔒 上锁 | 远程下发上锁指令 |
| 📊 状态查询 | 查询车辆门锁状态（信号接口） |
| 📱 快捷指令 | iPhone 快捷指令 / 锁屏按钮 / NFC 自动化接入 |
| 🔑 验证码登录 | 服务器端手机号+验证码登录，自动获取凭证（替代抓包） |

## 项目结构

```
car-project/
├── leapmotor_api.py       # 车控核心库（解锁/上锁/状态查询）
├── car_server.py          # HTTP 服务（快捷指令调用入口，端口 8898）
├── login_leapmotor.py     # 验证码登录链路（RSA 加密手机号 → 发码 → 登录）
├── config.example.py      # 配置文件模板（复制为 config.py 填写）
└── README.md
```

## 快速开始

### 1. 配置凭证

```bash
cp config.example.py config.py
# 编辑 config.py，填入真实凭证（获取方式见下文）
```

### 2. 本地测试

```bash
pip install requests
python leapmotor_api.py unlock   # 解锁
python leapmotor_api.py lock     # 上锁
```

### 3. 部署到服务器（宝塔）

1. 上传 `leapmotor_api.py` / `car_server.py` / `config.py` 到 `/www/wwwroot/car/`
2. 宝塔 **Python 项目管理器** 添加项目：启动命令 `python3 car_server.py`，端口 `8898`
3. Nginx 反向代理域名（如 `car.example.com`）到 `127.0.0.1:8898`，开启 SSL
4. 验证：`https://car.example.com/car/health` 返回 `{"code": 0, "message": "ok"}`

### 4. iPhone 快捷指令

| 操作 | URL |
|------|-----|
| 解锁 | `https://你的域名/car/unlock?key=你的API_KEY` |
| 上锁 | `https://你的域名/car/lock?key=你的API_KEY` |
| 查状态 | `https://你的域名/car/status?key=你的API_KEY` |

快捷指令：**获取URL内容** → **显示网页**（全屏绿=成功 / 全屏红=失败）

**NFC 自动化**：快捷指令 App → 自动化 → NFC → 扫描标签 → 运行快捷指令 → 关闭"运行前询问"

## 凭证获取（一次性，后续自动续期）

凭证来自智控 App（`com.leapauto.app`）登录会话，获取方式：

1. **Token / DeviceID / OPPWD**：抓包智控 App 的 `appremotectl` 请求
   - `TOKEN` = 请求头 `XFX-CDN-CROSS-NODE`
   - `DEVICE_ID` = 请求头 `APPImei`
   - `OPPWD` = 请求体 `oppwd` 字段（操作密码的加密值）
2. **SignKey / AccessToken / UserID**：登录响应（`account/v1/login`）中的 `signKeyBase64` / `accessToken` / `accountId`

> 也可以使用 `login_leapmotor.py` 通过验证码登录自动获取：
> ```bash
> python login_leapmotor.py 手机号            # 发送验证码
> python login_leapmotor.py 手机号 验证码 设备ID  # 验证码登录
> ```

## 协议说明（逆向成果）

### 车控接口

```
POST https://appgateway.leapmotor.com/app/app-control-service/v3/api/appremotectl
```

请求头：`APPPlatform / APPVersion / APPImei / C-VERSIONS / XFX-CDN-VRS / XFX-CDN-CROSS-NODE`

请求体（表单）：
```
timespan=<毫秒时间戳>&nonce=<随机数>&deviceID=<设备ID>&cmdid=110
&state={"value":"unlock"|"lock"}&carvin=<VIN>&oppwd=<加密密码>&signStr=<签名>
```

**signStr 签名算法**：
```python
signStr = md5(carvin + cmdid + deviceID + nonce + oppwd + '\n' + state + timespan + token)[8:24]
# 注意：oppwd 参与签名时带换行符 \n
```

### 状态查询接口（通用签名）

```
POST https://appgateway.leapmotor.com/app/app-signal-service/signal/info/query
```

**sign 签名算法**：所有参数（acceptLanguage/channel/deviceId/deviceType/nonce/source/timestamp/version/vin）按 key 字母排序，取值拼接，`HMAC-SHA256(signKey, 拼接串)`

### 登录链路

```
1. GET  https://appuser.leapmotor.cn/app-user/applogin/compliance/sendmessagecode?phoneNo=<RSA加密手机号>
2. POST https://appuser.leapmotor.cn/app-user/applogin/check_login_with_phone?phoneNoCiphertext=...&smsCode=...
3. POST https://app-gw-global-master.leapmotor.com/base/base-user/account/v1/login
```

手机号加密：**RSA-1024 PKCS1 v1.5**（公钥见 `login_leapmotor.py`），输出 base64url。

## 安全说明

- `config.py` 包含车控凭证，**已被 .gitignore 忽略，严禁提交**
- HTTP 接口必须带 `key` 鉴权，请使用强随机密钥
- 建议通过 Nginx 开启 HTTPS
- 车控接口有频率限制，请勿高频调用

## 免责声明

本项目仅供学习研究，使用造成的一切后果由使用者自行承担。
