"""Fail-closed VPS -> Windows UE Worker adapter.

Pinned to the VPS loopback end of the dedicated SSH reverse tunnel.
Never accepts a remote URL or arbitrary operation from an MCP caller.
"""
from __future__ import annotations

import json
import os
import re
import stat
import urllib.error
import urllib.request
from pathlib import Path

WORKER_ORIGIN = "http://127.0.0.1:18910"
READ_ROUTES = {
    "get_ue_worker_status": "/v1/status",
    "get_ue_worker_capabilities": "/v1/capabilities",
}
WRITE_ACTIONS = {"prepare_ue_workspace": "prepare_workspace"}
MAX_RESULT = 16384


class WorkerError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise WorkerError("redirect_not_allowed")


OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect()
)


def load_token(path=None):
    path = Path(path or os.getenv("DIRECTOR_UE_WORKER_TOKEN_FILE",
                                "/etc/director-ue-worker.token"))
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 128:
        raise WorkerError("worker_token_unconfigured")
    if stat.S_IMODE(path.stat().st_mode) & 0o007:
        raise WorkerError("insecure_token_permissions")
    token = path.read_text("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise WorkerError("invalid_worker_token")
    return token


def call_ue_worker(name, opener=None, token_file=None):
    """Only three known actions; do not relay arbitrary paths, commands or args."""
    if name not in READ_ROUTES and name not in WRITE_ACTIONS:
        return {"ok": False, "reason": "action_denied"}
    if os.getenv("DIRECTOR_UE_WORKER_ENABLED", "0") != "1":
        return {"ok": False, "reason": "ue_worker_not_enabled"}
    try:
        token = load_token(token_file)
        if name in READ_ROUTES:
            path, data, method = READ_ROUTES[name], None, "GET"
        else:
            path, method = "/v1/actions", "POST"
            data = json.dumps({"action": WRITE_ACTIONS[name]}).encode("ascii")
        url = WORKER_ORIGIN + path
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        with (opener or OPENER).open(req, timeout=8) as response:
            if response.geturl() != url:
                raise WorkerError("redirect_not_allowed")
            raw = response.read(MAX_RESULT + 1)
        if len(raw) > MAX_RESULT:
            raise WorkerError("worker_response_too_large")
        obj = json.loads(raw)
        if not isinstance(obj, dict) or type(obj.get("ok")) is not bool:
            raise WorkerError("invalid_worker_response")
        return obj
    except WorkerError as exc:
        return {"ok": False, "reason": str(exc)}
    except (OSError, TypeError, ValueError, urllib.error.URLError):
        return {"ok": False, "reason": "ue_worker_unavailable"}
