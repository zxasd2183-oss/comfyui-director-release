"""Director UE Windows worker: loopback-only, token-authenticated and allowlisted.

No general shell, Python execution, package installation or file upload endpoint.
The SSH -R tunnel is the only intended path from VPS to this process.
"""
from __future__ import annotations

import hmac
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 19010
MAX_BODY = 2048
ACTION_LOCK = threading.Lock()
NODE_ID = "ue-worker-01"


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def read_secret(path=None):
    raw_path = path or os.getenv("DIRECTOR_UE_TOKEN_FILE")
    if not raw_path:
        raise RuntimeError("DIRECTOR_UE_TOKEN_FILE is required")
    f = Path(raw_path)
    if f.is_symlink() or not f.is_file() or f.stat().st_size > 128:
        raise RuntimeError("invalid token file")
    token = f.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise RuntimeError("token must be 64 lowercase hex characters")
    return token


def workspace_root():
    raw = os.environ.get("DIRECTOR_UE_WORKSPACE", r"C:\DirectorVirtualStudio")
    root = Path(raw)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("workspace must be an absolute, normalized path")
    return root


def find_ue_installations():
    """Discover editor binaries; never download, install, or run UE."""
    candidates = []
    for env in ("UE_EDITOR_PATH",):
        path = os.environ.get(env)
        if path:
            candidates.append(Path(path))
    for base in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),):
        epic = Path(base) / "Epic Games"
        if epic.is_dir():
            for entry in sorted(epic.iterdir()):
                if entry.is_dir() and entry.name.startswith("UE_"):
                    candidates.append(entry / "Engine" / "Binaries" / "Win64" /
                                      "UnrealEditor.exe")
    found = []
    for candidate in candidates:
        try:
            if candidate.is_file():
                found.append({"editor_path": str(candidate.resolve())})
        except (OSError, ValueError):
            continue
    return found[:16]


def gpu_summary():
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"available": False}
    try:
        p = subprocess.run(
            [executable, "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if p.returncode != 0:
            return {"available": False}
        # Status data only. Do not return arbitrary command output.
        records = []
        for line in p.stdout.splitlines()[:8]:
            fields = [item.strip()[:120] for item in line.split(",")]
            if len(fields) == 3:
                records.append(dict(zip(("name", "vram_mib", "driver"), fields)))
        return {"available": bool(records), "devices": records}
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False}


def status():
    return {
        "ok": True, "node_id": NODE_ID, "platform": platform.system(),
        "hostname": platform.node()[:128], "timestamp": utcnow(),
        "python": platform.python_version(),
        "gpu": gpu_summary(), "ue": {"installations": find_ue_installations()},
        "workspace_exists": workspace_root().is_dir(),
        "control_mode": "allowlisted_only",
    }


def capabilities():
    return {
        "ok": True, "node_id": NODE_ID,
        "actions": ["prepare_workspace"],
        "supports_arbitrary_commands": False,
        "supports_unreal_install": False,
        "supports_rendering": False,
    }


def prepare_workspace():
    """Only create a fixed directory structure under configured workspace root."""
    root = workspace_root()
    subdirs = ("Characters", "Environments", "Animations", "Audio",
               "Sequences", "Cameras", "Python", "Render", "Outputs")
    root.mkdir(parents=True, exist_ok=True)
    for part in subdirs:
        (root / part).mkdir(exist_ok=True)
    return {"ok": True, "action": "prepare_workspace",
            "workspace": str(root), "directories": list(subdirs),
            "timestamp": utcnow()}


class Handler(BaseHTTPRequestHandler):
    server_version = "DirectorUEWorker/0.1"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Never log Authorization headers or request bodies.
        sys.stderr.write(f"[{utcnow()}] {self.client_address[0]} {fmt % args}\n")

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorize(self):
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + self.server.token
        return hmac.compare_digest(supplied.encode("utf-8", "ignore"),
                                   expected.encode("ascii"))

    def do_GET(self):
        if not self.authorize():
            self.send_json(401, {"ok": False, "reason": "unauthorized"})
        elif self.path == "/v1/status":
            self.send_json(200, status())
        elif self.path == "/v1/capabilities":
            self.send_json(200, capabilities())
        else:
            self.send_json(404, {"ok": False, "reason": "not_found"})

    def do_POST(self):
        if not self.authorize():
            self.send_json(401, {"ok": False, "reason": "unauthorized"})
            return
        if self.path != "/v1/actions":
            self.send_json(404, {"ok": False, "reason": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= length <= MAX_BODY:
                raise ValueError("invalid length")
            body = json.loads(self.rfile.read(length))
            if type(body) is not dict or set(body) != {"action"}:
                raise ValueError("invalid fields")
            if body["action"] != "prepare_workspace":
                self.send_json(403, {"ok": False, "reason": "action_denied"})
                return
            if not ACTION_LOCK.acquire(blocking=False):
                self.send_json(409, {"ok": False, "reason": "busy"})
                return
            try:
                self.send_json(200, prepare_workspace())
            finally:
                ACTION_LOCK.release()
        except (ValueError, UnicodeError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "reason": "invalid_request"})
        except OSError:
            self.send_json(500, {"ok": False, "reason": "workspace_unavailable"})


def main():
    if platform.system() != "Windows":
        raise SystemExit("This UE worker must run on Windows")
    token = read_secret()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.token = token
    print(f"{NODE_ID} listening on {HOST}:{PORT}", flush=True)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
