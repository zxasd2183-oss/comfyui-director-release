#!/usr/bin/env python3
"""Loopback-only GitHub OIDC notification -> unprivileged signed-APK mirror.

Never accepts uploads, arbitrary commands, pairing secrets, or URL inputs.
Starts the EXISTING read-only sync script after GitHub signature and claim
verification. Hourly timer remains an independent fallback.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
import sys
import threading

from jipite_oidc import AuthenticationFailure, verify

PORT = 8896
SYNC = "/opt/jipite-updates/sync-jipite-updates.py"
DIRECTORY = "/var/lib/jipite-updates"
_work_lock = threading.Lock()
_auth_lock = threading.Lock()


def synchronize():
    try:
        print("GitHub release notification verified; starting signed APK mirror", flush=True)
        result = subprocess.run(
            [sys.executable, SYNC, "--directory", DIRECTORY],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=180,
            check=False,
        )
        print("Immediate mirror result:", result.returncode, flush=True)
        # Sync logs contain only public release metadata, never bearer tokens.
        print(result.stdout[-3000:], flush=True)
    except Exception as exc:
        print("Immediate mirror unavailable; hourly fallback remains active:",
              type(exc).__name__, flush=True)
    finally:
        _work_lock.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "JipiteMirrorNotify/1.0"
    sys_version = ""

    def log_message(self, format, *args):
        # Never log request headers, Authorization, bearer tokens or raw bodies.
        print("Jipite notification request handled", flush=True)

    def respond(self, status: int, text: str):
        data = (json.dumps({"status": text}) + "\n").encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.respond(405, "method_not_allowed")

    def do_POST(self):
        if self.path != "/notify":
            return self.respond(404, "not_found")
        try:
            size = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= size <= 512:
                return self.respond(413, "invalid_request_size")
            # Read the expected tiny JSON body; never read a larger stream.
            body = self.rfile.read(size)
            if body.strip() not in (b"", b"{}"):
                return self.respond(400, "invalid_body")
            header = self.headers.get("Authorization", "")
            if len(header) > 11000 or not header.startswith("Bearer "):
                return self.respond(401, "authentication_required")
            # Serialize verification to bound simultaneous JWKS fetches.
            if not _auth_lock.acquire(blocking=False):
                return self.respond(429, "try_again")
            try:
                verify(header[7:])
            finally:
                _auth_lock.release()
        except (AuthenticationFailure, ValueError, OSError, json.JSONDecodeError,
                subprocess.TimeoutExpired):
            # Fail closed and reveal no validation details to the caller.
            return self.respond(403, "not_authorized")
        except Exception:
            return self.respond(503, "verification_unavailable")
        if not _work_lock.acquire(blocking=False):
            return self.respond(202, "mirror_already_running")
        threading.Thread(target=synchronize, daemon=True).start()
        return self.respond(202, "sync_accepted")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    if args.port < 1024 or args.port > 65535:
        raise SystemExit("Port out of range")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"Jipite OIDC sync notification listening on 127.0.0.1:{args.port}",
          flush=True)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
