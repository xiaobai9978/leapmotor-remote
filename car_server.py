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
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Python 3.6 兼容的多线程服务器（3.7+ 才有内置 ThreadingHTTPServer）"""
    daemon_threads = True

sys.path.insert(0, '/www/wwwroot/car/')
import config
import leapmotor_api as api

API_KEY = config.API_KEY

# ===== 状态页（快捷指令显示用：全屏绿=成功 / 全屏红=失败）=====
PAGE_OK = '<html><head><meta charset="utf-8"><style>body{background:#0a0;color:#fff;font-size:60px;text-align:center;padding-top:40vh;font-family:sans-serif}</style></head><body>%s</body></html>'
PAGE_FAIL = '<html><head><meta charset="utf-8"><style>body{background:#c00;color:#fff;font-size:40px;text-align:center;padding-top:35vh;font-family:sans-serif}</style></head><body>%s<br><small>%s</small></body></html>'


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
        path = urllib.parse.urlparse(self.path).path
        if path == '/car/health':
            self._json({'code': 0, 'message': 'ok'})
            return
        if path in ('/car/unlock', '/car/lock', '/car/status'):
            if not self._check_key():
                self._json({'code': 403, 'message': 'key错误'})
                return
            if path == '/car/unlock':
                ok, mid, info = api.send_control('unlock')
                if ok:
                    self._send(200, PAGE_OK % '已解锁', 'text/html; charset=utf-8')
                else:
                    self._send(200, PAGE_FAIL % ('解锁失败', info), 'text/html; charset=utf-8')
                return
            if path == '/car/lock':
                ok, mid, info = api.send_control('lock')
                if ok:
                    self._send(200, PAGE_OK % '已上锁', 'text/html; charset=utf-8')
                else:
                    self._send(200, PAGE_FAIL % ('上锁失败', info), 'text/html; charset=utf-8')
                return
            if path == '/car/status':
                locked, data = api.get_vehicle_status()
                if locked is not None:
                    txt = '已锁定' if locked else '已解锁'
                    self._send(200, PAGE_OK % txt, 'text/html; charset=utf-8')
                else:
                    self._send(200, PAGE_FAIL % ('查询失败', str(data)[:60]), 'text/html; charset=utf-8')
                return
        self._json({'code': 404, 'message': 'not found'})


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8898
    print('[*] 零跑车控服务启动: 0.0.0.0:' + str(port))
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
