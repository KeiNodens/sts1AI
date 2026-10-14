"""Communication Mod 子プロセス + HTTP 制御面.

CommMod が起動する子プロセスとして動く。stdin から state JSON を受け取り、
HTTP :15531 で外部(MCP/LLM)へ公開する。コマンドは HTTP POST で受けて
stdout 経由でゲームへ送る。

API:
  GET  /state          → 最新の state JSON(無ければ 204)
  POST /cmd            → {"line": "PLAY 5"} をキューへ
  GET  /health         → {"alive": true, "has_state": bool}
"""
import sys, json, threading, queue, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("STS1_BRIDGE_PORT", "15531"))

_lock = threading.Lock()
_latest_state = None
_cmd_q = queue.Queue()

# javaw の子プロセスでは sys.stdout.flush() が OSError を出すことがあるため
# fd 1 への直接 write に統一する
_OUT_FD = sys.stdout.fileno()
_IN_FD = sys.stdin.fileno()


def _write_line(s: str):
    os.write(_OUT_FD, (s + "\n").encode("utf-8"))


def stdin_reader():
    global _latest_state
    buf = b""
    while True:
        chunk = os.read(_IN_FD, 65536)
        if not chunk:
            os._exit(0)  # 親(ゲーム)終了で stdin 切断 → 自分も終了
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                # 日本語 Windows のゲーム出力は UTF-8 以外が混ざることがある
                obj = json.loads(line.decode("utf-8", errors="replace"))
                with _lock:
                    _latest_state = obj
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass  # 非 JSON 行(ログ等)は無視


def stdout_writer():
    _write_line("ready")  # 起動ハンドシェイク
    while True:
        _write_line(_cmd_q.get())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None):
        body = json.dumps(obj or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/state":
            with _lock:
                st = _latest_state
            if st is None:
                self._send(204)
            else:
                self._send(200, st)
        elif self.path == "/health":
            with _lock:
                self._send(200, {"alive": True, "has_state": _latest_state is not None})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/cmd":
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            line = body.get("line", "").strip()
            if line:
                _cmd_q.put(line)
                self._send(200, {"queued": line})
            else:
                self._send(400, {"error": "empty command"})
        else:
            self._send(404, {"error": "not found"})


class Server(ThreadingHTTPServer):
    allow_reuse_address = False  # ゾンビ bridge の二重 bind を防ぐ
    daemon_threads = True


if __name__ == "__main__":
    threading.Thread(target=stdin_reader, daemon=True).start()
    threading.Thread(target=stdout_writer, daemon=True).start()
    try:
        Server(("127.0.0.1", PORT), Handler).serve_forever()
    except OSError as e:
        # ポート競合 = 既に生きている bridge がいる → こちらは終了
        sys.stderr.write(f"bridge: port {PORT} busy ({e}), exiting\n")
        os._exit(1)
