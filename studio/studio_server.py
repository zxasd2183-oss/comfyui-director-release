"""Director Studio V0.8: SSH-only real-time supervisory HTTP console.

Service binds 127.0.0.1:8900. Never expose it via Nginx before implementing
owner authentication. Studio interventions edit an audited scheduling ledger,
NOT the live ComfyUI queue or GPU power.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from studio_core import StudioError, connect, decide, snapshot
from studio_backend import query

BASE = Path(__file__).resolve().parent
HOSTS = {"127.0.0.1:8900", "localhost:8900"}
MAX_BODY = 8192
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; "
       "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")

class Poller:
    def __init__(self, interval=5, probe=query):
        self.interval, self.probe = interval, probe
        self.lock = threading.Lock()
        self.data = {
            "gpu_power": {"ok": False, "reason": "not_checked"},
            "comfy_queue": {"ok": False, "reason": "not_checked"},
            "last_checked": None,
        }
        self.running = True

    def sample(self):
        result = {}
        for name, tool in (("gpu_power", "get_gpu_power_status"),
                           ("comfy_queue", "get_queue_summary")):
            try:
                value = self.probe(tool)
                result[name] = value if isinstance(value, dict) else {
                    "ok": False, "reason": "unexpected_backend_result"}
            except Exception:
                result[name] = {"ok": False, "reason": "backend_unavailable"}
        with self.lock:
            self.data = {**result, "last_checked": int(time.time())}

    def loop(self):
        while self.running:
            self.sample()
            for _ in range(int(self.interval * 10)):
                if not self.running:
                    break
                time.sleep(0.1)

    def current(self):
        with self.lock:
            return dict(self.data)


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, db_path, poller=None, bind=("127.0.0.1", 8900)):
        if bind[0] != "127.0.0.1":
            raise RuntimeError("Only 127.0.0.1 binding is permitted")
        self.db_path = db_path
        self.poller = poller if poller is not None else Poller()
        self.csrf_token = secrets.token_urlsafe(32)
        self.is_running = True
        with closing(connect(self.db_path)):
            pass
        super().__init__(bind, StudioHandler)

    def stop(self):
        self.is_running = False
        self.poller.running = False
        self.shutdown()


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "DirectorStudio/0.8"
    sys_version = ""

    def log_message(self, *args):
        # Do not persist user note contents, query strings or private auth data.
        return

    def headers_safe(self):
        host = self.headers.get("Host", "")
        return host in HOSTS and self.client_address[0] == "127.0.0.1"

    def common_headers(self, mime):
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)

    def reply(self, code, value):
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.common_headers("application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def file(self, filename, mime):
        path = BASE / filename
        raw = path.read_bytes()
        self.send_response(200)
        self.common_headers(mime)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def fresh_snapshot(self):
        with closing(connect(self.server.db_path)) as db:
            value = snapshot(db)
        value["live"] = self.server.poller.current()
        value["sample_age_seconds"] = (
            max(0, int(time.time()) - value["live"]["last_checked"])
            if value["live"]["last_checked"] is not None else None)
        return value

    def do_GET(self):
        if not self.headers_safe():
            return self.reply(403, {"ok": False, "reason": "invalid_host"})
        path = urlsplit(self.path).path
        if path == "/":
            return self.file("index.html", "text/html; charset=utf-8")
        if path == "/studio.css":
            return self.file("studio.css", "text/css; charset=utf-8")
        if path == "/studio.js":
            return self.file("studio.js", "application/javascript; charset=utf-8")
        if path == "/api/v1/bootstrap":
            return self.reply(200, {"ok": True, "csrf": self.server.csrf_token,
                                    "mode": "ssh_only_local_supervisor"})
        if path == "/api/v1/snapshot":
            return self.reply(200, self.fresh_snapshot())
        if path != "/api/v1/stream":
            return self.reply(404, {"ok": False, "reason": "not_found"})
        self.send_response(200)
        self.common_headers("text/event-stream; charset=utf-8")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while self.server.is_running:
                data = json.dumps(self.fresh_snapshot(), ensure_ascii=False,
                                  separators=(",", ":"))
                self.wfile.write(("event: snapshot\ndata: " + data + "\n\n").encode("utf-8"))
                self.wfile.flush()
                time.sleep(2)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_POST(self):
        if not self.headers_safe():
            return self.reply(403, {"ok": False, "reason": "invalid_host"})
        if urlsplit(self.path).path != "/api/v1/action":
            return self.reply(404, {"ok": False, "reason": "not_found"})
        origin = self.headers.get("Origin", "")
        if origin not in ("http://127.0.0.1:8900", "http://localhost:8900"):
            return self.reply(403, {"ok": False, "reason": "invalid_origin"})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.reply(415, {"ok": False, "reason": "json_only"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.reply(400, {"ok": False, "reason": "invalid_content_length"})
        if not 1 <= length <= MAX_BODY:
            return self.reply(413, {"ok": False, "reason": "invalid_request_size"})
        try:
            data = json.loads(self.rfile.read(length))
            if (not isinstance(data, dict) or
                    set(data) - {"csrf", "action", "shot_id", "revision", "reason"}):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self.reply(400, {"ok": False, "reason": "invalid_json"})
        if not secrets.compare_digest(str(data.get("csrf", "")), self.server.csrf_token):
            return self.reply(403, {"ok": False, "reason": "csrf_denied"})
        try:
            with connect(self.server.db_path) as db:
                out = decide(db, data.get("action"), shot_id=data.get("shot_id"),
                             revision=data.get("revision"), reason=data.get("reason", ""))
        except StudioError as exc:
            return self.reply(409, {"ok": False, "reason": str(exc)})
        except Exception:
            return self.reply(503, {"ok": False, "reason": "studio_storage_unavailable"})
        return self.reply(200, out)


def main():
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument("--db", default=os.environ.get(
        "DIRECTOR_STUDIO_DB", "/var/lib/director-studio/studio.sqlite"))
    args = parser.parse_args()
    server = StudioServer(args.db)
    worker = threading.Thread(target=server.poller.loop, daemon=True)
    worker.start()
    print("Director Studio V0.8 listening ONLY on 127.0.0.1:8900", flush=True)
    print("Connect using SSH local port forwarding; never publish this HTTP port", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.is_running = False
        server.poller.running = False
        server.server_close()


if __name__ == "__main__":
    main()
