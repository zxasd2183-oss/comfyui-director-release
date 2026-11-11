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

from ue_jobs import JobManager, JobError
from ue_logs import log_tail

HOST = "127.0.0.1"
PORT = 19010
MAX_BODY = 24576
ACTION_LOCK = threading.Lock()
NODE_ID = "ue-worker-01"
JOB_MANAGER = None


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def read_secret(path=None):
    raw_path = (path or os.getenv("DIRECTOR_UE_TOKEN_FILE") or
                str(Path(os.getenv("PROGRAMDATA", r"C:\\ProgramData")) /
                    "DirectorUEWorker" / "worker.token"))
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


def signed_update_status():
    """Read only the SYSTEM updater's small non-secret status receipt."""
    source = Path(__file__).resolve().parent / "signed-update-status.json"
    try:
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 2048:
            return {"status": "not_configured"}
        item = json.loads(source.read_text(encoding="utf-8"))
        if type(item) is not dict:
            return {"status": "invalid_receipt"}
        # Never forward arbitrary strings or raw updater logs through MCP.
        allowed = ("status", "version", "reason", "code", "recovered")
        return {name: item[name] for name in allowed
                if name in item and type(item[name]) in (str, bool)}
    except (OSError, UnicodeError, ValueError, TypeError):
        return {"status": "invalid_receipt"}


def status():
    active_job_id = None
    if JOB_MANAGER is not None:
        with JOB_MANAGER.lock:
            active_job_id = JOB_MANAGER.active
    return {
        "active_job_id": active_job_id,
        "signed_update": signed_update_status(),
        "ok": True, "node_id": NODE_ID, "platform": platform.system(),
        "hostname": platform.node()[:128], "timestamp": utcnow(),
        "python": platform.python_version(),
        "gpu": gpu_summary(), "ue": {"installations": find_ue_installations()},
        "workspace_exists": workspace_root().is_dir(),
        "control_mode": "allowlisted_only",
        "worker_version": "0.6.0",
    }


def capabilities():
    return {
        "ok": True, "node_id": NODE_ID,
        "actions": ["prepare_workspace"],
        "jobs": ["build_episode_timeline", "build_stage_cameras", "render_previs_stills"],
        "job_status_route": "/v2/jobs/<job_id>",
        "job_logs_route": "/v3/jobs/<job_id>/logs/<kind>",
        "job_cancel_route": "/v3/jobs/<job_id>/cancel",
        "supports_job_cancel": True,
        "supports_arbitrary_commands": False,
        "supports_unreal_install": False,
        "supports_rendering": False,
        "supports_previs_stills": True,
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
    server_version = "DirectorUEWorker/0.6"
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
        elif re.fullmatch(r"/v2/jobs/[a-f0-9]{32}", self.path):
            try:
                self.send_json(200, JOB_MANAGER.lookup(self.path.rsplit("/", 1)[-1]))
            except JobError as exc:
                self.send_json(404, {"ok": False, "reason": str(exc)})
        elif re.fullmatch(r"/v3/jobs/[a-f0-9]{32}/logs/[a-z0-9_]{1,20}", self.path):
            parts = self.path.split("/")
            try:
                self.send_json(200, log_tail(JOB_MANAGER, parts[3], parts[5]))
            except JobError as exc:
                self.send_json(404, {"ok": False, "reason": str(exc)})
            except OSError:
                self.send_json(500, {"ok": False, "reason": "job_log_unavailable"})
        else:
            self.send_json(404, {"ok": False, "reason": "not_found"})

    def do_POST(self):
        if not self.authorize():
            self.send_json(401, {"ok": False, "reason": "unauthorized"})
            return
        cancel_match = re.fullmatch(r"/v3/jobs/([a-f0-9]{32})/cancel", self.path)
        if cancel_match:
            # Cancellation is ID-bound and intentionally accepts NO body.
            if (self.headers.get("Content-Length", "0") != "0" or
                    self.headers.get("Transfer-Encoding")):
                self.send_json(400, {"ok": False, "reason": "invalid_request"})
                return
            try:
                self.send_json(202, JOB_MANAGER.cancel(cancel_match.group(1)))
            except JobError as exc:
                self.send_json(404, {"ok": False, "reason": str(exc)})
            return
        if self.path not in ("/v1/actions", "/v2/jobs"):
            self.send_json(404, {"ok": False, "reason": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= length <= MAX_BODY:
                raise ValueError("invalid length")
            body = json.loads(self.rfile.read(length))
            if self.path == "/v2/jobs":
                try:
                    self.send_json(202, JOB_MANAGER.submit(body))
                except JobError as exc:
                    reason = str(exc)
                    self.send_json(409 if reason == "ue_worker_busy" else 400,
                                   {"ok": False, "reason": reason})
                return
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
    global JOB_MANAGER
    JOB_MANAGER = JobManager(workspace_root)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.token = token
    print(f"{NODE_ID} listening on {HOST}:{PORT}", flush=True)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
