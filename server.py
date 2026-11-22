"""Tiny local server so the browser extension can send links to the app.

Safety: listens on 127.0.0.1 only, requires a custom header (web pages can't
send it cross-origin without a CORS preflight, which we never approve) and
checks the Host header (blocks DNS-rebinding)."""
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9614


class Handler(BaseHTTPRequestHandler):
    inbox = queue.Queue()

    def _ok_host(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def do_GET(self):
        if self._ok_host() and self.path == "/ping":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"simpledm")
        else:
            self.send_error(403)

    def do_POST(self):
        if not self._ok_host() or self.path != "/add" or self.headers.get("X-SimpleDM") != "1":
            return self.send_error(403)
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(min(n, 1 << 20)) or b"{}")
            assert isinstance(data.get("url"), str)
        except Exception:
            return self.send_error(400)
        Handler.inbox.put(data)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def start():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return Handler.inbox
