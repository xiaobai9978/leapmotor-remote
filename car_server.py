# -*- coding: utf-8 -*-
# 零跑车控 HTTP 服务（宝塔部署，Python 3.6+）
# 接口：
#   GET /car/unlock?key=xxx   解锁
#   GET /car/lock?key=xxx     上锁
#   GET /car/status?key=xxx   查询门锁状态
#   GET /car/health           健康检查
# 启动: python3 car_server.py  （端口 8898）
import json
import urllib.parse
import sys
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Python 3.6 兼容的多线程服务器（3.7+ 才有内置 ThreadingHTTPServer）"""
    daemon_threads = True

sys.path.insert(0, '/www/wwwroot/car/')
import config
import leapmotor_api as api

API_KEY = config.API_KEY

# ===== 状态页（快捷指令显示用：全屏绿=成功 / 全屏红=失败 + 一键修复按钮）=====
PAGE_OK = '''<html><head><meta charset="utf-8"><style>
body{background:#0a0;color:#fff;font-size:60px;text-align:center;padding-top:32vh;font-family:sans-serif;margin:0}
.btn{display:inline-block;margin:26px auto 0;padding:14px 40px;font-size:18px;border:none;border-radius:10px;cursor:pointer;color:#fff;background:#2471a3}
#m{display:block;margin-top:14px;font-size:14px;color:#eee}
</style></head><body>
%s<br>
<button class="btn" onclick="doFix()">一键修复（换凭证+重启）</button>
<span id="m"></span>
<script>
var K="%s";
function doFix(){if(!confirm('确定一键修复？约5秒后恢复'))return;document.getElementById('m').textContent='步骤1/2 获取新凭证...';fetch('/car/recred?key='+K).then(function(r){return r.json()}).then(function(d){document.getElementById('m').textContent='凭证:'+d.message+' 步骤2/2 重启程序...';fetch('/car/restart?key='+K).then(function(r){return r.text()}).then(function(t){document.getElementById('m').textContent=t})}).catch(function(){document.getElementById('m').textContent='凭证获取失败，直接重启...';fetch('/car/restart?key='+K).then(function(r){return r.text()}).then(function(t){document.getElementById('m').textContent=t})});}
</script></body></html>'''
PAGE_FAIL = '''<html><head><meta charset="utf-8"><style>
body{background:#c00;color:#fff;font-size:40px;text-align:center;padding-top:28vh;font-family:sans-serif;margin:0}
.btn{display:inline-block;margin:26px auto 0;padding:14px 40px;font-size:18px;border:none;border-radius:10px;cursor:pointer;color:#fff;background:#2471a3}
#m{display:block;margin-top:14px;font-size:14px;color:#ffd}
</style></head><body>
%s<br><small>%s</small><br>
<button class="btn" onclick="doFix()">一键修复（换凭证+重启）</button>
<span id="m"></span>
<script>
var K="%s";
function doFix(){if(!confirm('确定一键修复？约5秒后恢复'))return;document.getElementById('m').textContent='步骤1/2 获取新凭证...';fetch('/car/recred?key='+K).then(function(r){return r.json()}).then(function(d){document.getElementById('m').textContent='凭证:'+d.message+' 步骤2/2 重启程序...';fetch('/car/restart?key='+K).then(function(r){return r.text()}).then(function(t){document.getElementById('m').textContent=t})}).catch(function(){document.getElementById('m').textContent='凭证获取失败，直接重启...';fetch('/car/restart?key='+K).then(function(r){return r.text()}).then(function(t){document.getElementById('m').textContent=t})});}
</script></body></html>'''

# ===== 自动修复提示页（凭证失效时：后台修复 + 10 秒自动重载）=====
PAGE_AUTOFIX = '''<html><head><meta charset="utf-8"><style>
body{background:#2471a3;color:#fff;font-size:30px;text-align:center;padding-top:32vh;font-family:sans-serif;margin:0}
small{font-size:15px;color:#ddeeff}
</style></head><body>
🔧 正在自动修复凭证<br><small>已刷新凭证并重启程序，页面约 10 秒后自动重试...</small>
<script>setTimeout(function(){location.reload()}, 10000);</script>
</body></html>'''

# ===== 自动故障恢复（凭证类错误 → 后台刷新 + 重启，60 秒防重复）=====
_last_fix_time = 0.0
_fix_lock = threading.Lock()


def _is_cred_err(m):
    """凭证类错误判定（风控提示不触发，重启也白搭）"""
    if '累计' in m or '3次' in m:
        return False
    return any(k in m for k in ('密码错误', 'TOKEN', '过期', '登录', '校验失败'))


def _restart_process():
    """后台重启：2 秒后杀旧进程，3 秒后起新进程（约 5 秒恢复）"""
    subprocess.Popen(['bash', '-c',
        'sleep 2; pkill -f "[c]ar_server.py"; sleep 1; '
        'cd /www/wwwroot/car && '
        'setsid /www/server/pyporject_evn/3.10.21/bin/python3 car_server.py > /dev/null 2>&1 &'],
        start_new_session=True)


def _auto_fix(msg):
    """凭证类错误 → 后台线程：刷新凭证 + 重启进程（60 秒内不重复）"""
    global _last_fix_time
    with _fix_lock:
        if time.time() - _last_fix_time < 60:
            return
        _last_fix_time = time.time()

    def work():
        t0 = time.time()
        try:
            ok, info = api._refresh_token_inner()
            sys.stderr.write('[auto-fix] %s → 刷新: %s\n' % (msg[:30], info))
            _restart_process()
            sys.stderr.write('[auto-fix] 已刷新并重启，耗时 %.1f 秒\n' % (time.time() - t0))
        except Exception as e:
            sys.stderr.write('[auto-fix] 异常: %s\n' % str(e))

    threading.Thread(target=work, daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write('[car] %s\n' % (fmt % args))

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj):
        self._send(200, json.dumps(obj, ensure_ascii=False))

    def _check_key(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return q.get('key', [''])[0] == API_KEY

    def do_GET(self):
        try:
            self._do_get()
        except Exception as e:
            # 兜底：任何未捕获异常都返回错误页，避免空响应导致 nginx 502
            import traceback
            traceback.print_exc()
            try:
                self._send(200, PAGE_FAIL % ('服务异常', str(e)[:60]), 'text/html; charset=utf-8')
            except Exception:
                pass

    def _do_get(self):
        path = urllib.parse.urlparse(self.path).path
        if path == '/car/health':
            self._json({'code': 0, 'message': 'ok'})
            return
        if path == '/car/restart':
            if not self._check_key():
                self._json({'code': 403, 'message': 'key错误'})
                return
            # 先响应客户端，再后台杀旧起新（约 5 秒恢复）
            self._send(200, '正在重启，约 5 秒后恢复...', 'text/plain; charset=utf-8')
            subprocess.Popen(['bash', '-c',
                'sleep 2; pkill -f "[c]ar_server.py"; sleep 1; '
                'cd /www/wwwroot/car && '
                'setsid /www/server/pyporject_evn/3.10.21/bin/python3 car_server.py > /dev/null 2>&1 &'],
                start_new_session=True)
            return
        if path == '/car/recred':
            if not self._check_key():
                self._json({'code': 403, 'message': 'key错误'})
                return
            ok, info = api._refresh_token_inner()
            self._json({'code': 0 if ok else 1, 'message': info})
            return
        if path in ('/car/unlock', '/car/lock', '/car/status'):
            if not self._check_key():
                self._json({'code': 403, 'message': 'key错误'})
                return
            if path == '/car/unlock':
                ok, mid, info = api.send_control('unlock')
                if ok:
                    self._send(200, PAGE_OK % ('已解锁', API_KEY), 'text/html; charset=utf-8')
                elif _is_cred_err(str(info)):
                    _auto_fix(str(info))
                    self._send(200, PAGE_AUTOFIX, 'text/html; charset=utf-8')
                else:
                    self._send(200, PAGE_FAIL % ('解锁失败', info, API_KEY), 'text/html; charset=utf-8')
                return
            if path == '/car/lock':
                ok, mid, info = api.send_control('lock')
                if ok:
                    self._send(200, PAGE_OK % ('已上锁', API_KEY), 'text/html; charset=utf-8')
                elif _is_cred_err(str(info)):
                    _auto_fix(str(info))
                    self._send(200, PAGE_AUTOFIX, 'text/html; charset=utf-8')
                else:
                    self._send(200, PAGE_FAIL % ('上锁失败', info, API_KEY), 'text/html; charset=utf-8')
                return
            if path == '/car/status':
                locked, data = api.get_vehicle_status()
                if locked is not None:
                    txt = '已锁定' if locked else '已解锁'
                    self._send(200, PAGE_OK % (txt, API_KEY), 'text/html; charset=utf-8')
                else:
                    info = str(data.get('message', data)) if isinstance(data, dict) else str(data)
                    if _is_cred_err(info):
                        _auto_fix(info)
                        self._send(200, PAGE_AUTOFIX, 'text/html; charset=utf-8')
                    else:
                        self._send(200, PAGE_FAIL % ('查询失败', info[:60], API_KEY), 'text/html; charset=utf-8')
                return
        self._json({'code': 404, 'message': 'not found'})


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8898
    print('[*] 零跑车控服务启动: 0.0.0.0:' + str(port))
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
