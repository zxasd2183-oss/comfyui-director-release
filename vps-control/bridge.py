#!/usr/bin/env python3
"""Read-only MCP boundary gateway for the Director Ubuntu VPS.

No credentials are exposed, no write tools exist upstream. Only a secret URL
path is accepted. For short-lived testing; use OAuth for production.
"""
import argparse
import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MAX_BODY = 256 * 1024
MAX_RESPONSE = 1024 * 1024
MAX_CONCURRENT = 12
LIMIT = threading.BoundedSemaphore(MAX_CONCURRENT)


def build_handler(token: str, upstream: str = "http://127.0.0.1:8890/mcp"):
    expected = "/mcp/" + token

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            # Never log the request URI (which embeds the bearer secret).
            return

        def reply(self, code, body=b""):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def dispatch(self):
            target = urlsplit(self.path)
            authorized = hmac.compare_digest(target.path.encode(), expected.encode())
            if not authorized or target.query or self.headers.get("Origin"):
                return self.reply(404, b'{"error":"not_found"}')
            if self.command not in ("POST", "GET", "DELETE"):
                return self.reply(405, b'{"error":"method_not_allowed"}')
            if not LIMIT.acquire(blocking=False):
                return self.reply(429, b'{"error":"busy"}')
            try:
                data = None
                if self.command == "POST":
                    if self.headers.get("Transfer-Encoding"):
                        return self.reply(400, b'{"error":"invalid_encoding"}')
                    try:
                        size = int(self.headers.get("Content-Length", "-1"))
                    except ValueError:
                        size = -1
                    if not 0 <= size <= MAX_BODY:
                        return self.reply(413, b'{"error":"invalid_size"}')
                    if "application/json" not in self.headers.get("Content-Type", "").lower():
                        return self.reply(415, b'{"error":"invalid_content_type"}')
                    data = self.rfile.read(size)
                # Allow only transport-related headers; rewrite Host to localhost.
                headers = {"Host": urlsplit(upstream).netloc,
                           "Accept": self.headers.get("Accept", "application/json, text/event-stream")}
                if self.command == "POST":
                    headers["Content-Type"] = "application/json"
                for name in ("Mcp-Protocol-Version", "Mcp-Session-Id"):
                    value = self.headers.get(name)
                    if value:
                        headers[name] = value
                request = Request(upstream, data=data, headers=headers, method=self.command)
                try:
                    with urlopen(request, timeout=20) as response:
                        code = response.status
                        body = response.read(MAX_RESPONSE + 1)
                        response_type = response.headers.get("Content-Type", "application/json")
                        session_id = response.headers.get("Mcp-Session-Id")
                except HTTPError as err:
                    code = err.code
                    body = err.read(MAX_RESPONSE + 1)
                    response_type = err.headers.get("Content-Type", "application/json")
                    session_id = err.headers.get("Mcp-Session-Id")
                if len(body) > MAX_RESPONSE or "text/event-stream" in response_type:
                    # This first test bridge is JSON-response-only; no SSE streaming.
                    return self.reply(502, b'{"error":"unsupported_transport"}')
                self.send_response(code)
                self.send_header("Content-Type", response_type)
                if session_id:
                    self.send_header("Mcp-Session-Id", session_id)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
            except (OSError, URLError, TimeoutError, ValueError):
                self.reply(502, b'{"error":"upstream_unavailable"}')
            finally:
                LIMIT.release()

        def do_POST(self): self.dispatch()
        def do_GET(self): self.dispatch()
        def do_DELETE(self): self.dispatch()
        def do_PUT(self): self.dispatch()
        def do_PATCH(self): self.dispatch()
        def do_OPTIONS(self): self.dispatch()

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8891)
    ap.add_argument("--token-file", default="/etc/comfyui-director-bridge.token")
    args = ap.parse_args()
    token_path = Path(args.token_file)
    token = token_path.read_text(encoding="ascii").strip()
    if len(token) < 48 or any(c not in "0123456789abcdef" for c in token):
        raise SystemExit("Invalid token file, expected at least 48 hexadecimal characters")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), build_handler(token))
    server.daemon_threads = True
    print(f"Director VPS MCP bridge listening only on 127.0.0.1:{args.port}", flush=True)
    server.serve_forever(poll_interval=0.3)


if __name__ == "__main__":
    main()
