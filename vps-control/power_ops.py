"""Local-only CompShare GPU power controller. NEVER expose this module as an anonymous MCP tool.

Read-only inspection can be reused by an authenticated MCP API later.
Actual start/stop is invoked only by powerctl.py with local interactive confirmation.
"""
from __future__ import annotations

import os
import logging
import re
import stat
from pathlib import Path
import urllib.error
import urllib.request

VALID_ACTIONS = {"start", "stop"}
ENV_KEYS = {"COMP_PUBLIC_KEY", "COMP_PRIVATE_KEY", "COMP_UHOST_ID",
            "COMP_REGION", "COMP_ZONE"}

class PowerError(Exception):
    """Safe failure; the message never includes provider response or credentials."""


def read_env_file(path: str = "/etc/comfyui-director-control.env", *,
                  validate_file_mode: bool = True) -> dict:
    file = Path(path)
    mode = stat.S_IMODE(file.stat().st_mode)
    if validate_file_mode and mode & 0o077:
        raise PowerError("Credential file permissions must be 0600")
    config = {}
    for raw_line in file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise PowerError("Invalid config line")
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in ENV_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if "\x00" in value:
            raise PowerError("Invalid config value")
        config[key] = value
    # No fallback to broad/default region; this is a billable/destructive operation.
    missing = [k for k in ("COMP_PUBLIC_KEY", "COMP_PRIVATE_KEY",
                         "COMP_UHOST_ID", "COMP_REGION", "COMP_ZONE")
               if not config.get(k)]
    if missing:
        raise PowerError("Power configuration incomplete: " + ", ".join(missing))
    if not re.fullmatch(r"[a-z0-9-]+", config["COMP_REGION"]):
        raise PowerError("Invalid region")
    if not re.fullmatch(r"[a-z0-9-]+", config["COMP_ZONE"]):
        raise PowerError("Invalid zone")
    return config



def read_systemd_credential_env(credential_file: str,
                               credential_directory: str,
                               source_file: str = "/etc/comfyui-director-control.env",
                               expected_source_uid: int = 0) -> dict:
    """Load a systemd LoadCredential copy, validating its private source.

    systemd protects the runtime credential with a private service namespace.
    Verify the runtime file is the directorenv credential within the service
    directory, AND ensure the root-owned original remains mode 0600.
    The normal CLI read_env_file() retains strict mode enforcement.
    """
    if not credential_file or not credential_directory:
        raise PowerError("Systemd credential environment not configured")
    runtime = Path(credential_file)
    directory = Path(credential_directory)
    if runtime.name != "directorenv" or runtime.is_symlink():
        raise PowerError("Unexpected runtime credential file")
    try:
        resolved_runtime = runtime.resolve(strict=True)
        resolved_directory = directory.resolve(strict=True)
    except OSError:
        raise PowerError("Systemd credential path unavailable") from None
    if resolved_runtime.parent != resolved_directory:
        raise PowerError("Systemd credential outside runtime directory")
    if not resolved_runtime.is_file():
        raise PowerError("Invalid runtime credential")
    try:
        source = Path(source_file)
        if source.is_symlink():
            raise PowerError("Source credential cannot be symlink")
        srcstat = source.stat()
    except OSError:
        raise PowerError("Original credential file not accessible") from None
    if (not stat.S_ISREG(srcstat.st_mode) or srcstat.st_uid != expected_source_uid
            or stat.S_IMODE(srcstat.st_mode) & 0o077):
        raise PowerError("Original credential must be root-owned and mode 0600")
    return read_env_file(str(resolved_runtime), validate_file_mode=False)

def silence_sdk_logging():
    # UCloud's own documentation documents this logger switch. The Describe
    # response contains secrets not intended for CLI output or journald.
    logging.getLogger('ucloud').disabled = True


def create_provider_client(config: dict):
    silence_sdk_logging()
    from ucloud.client import Client
    return Client({
        "region": config["COMP_REGION"],
        "public_key": config["COMP_PUBLIC_KEY"],
        "private_key": config["COMP_PRIVATE_KEY"],
        "base_url": "https://api.compshare.cn",
    })


def get_provider_state(config: dict, client=None) -> dict:
    silence_sdk_logging()
    try:
        client = client or create_provider_client(config)
        response = client.ucompshare().invoke("DescribeCompShareInstance", {
            "Region": config["COMP_REGION"],
            "Zone": config["COMP_ZONE"],
            "UHostIds": [config["COMP_UHOST_ID"]],
        })
        if not isinstance(response, dict) or response.get("RetCode") != 0:
            raise PowerError("Instance status request was rejected")
        hits = [item for item in response.get("UHostSet", [])
                if isinstance(item, dict) and item.get("UHostId") == config["COMP_UHOST_ID"]]
        if len(hits) != 1:
            raise PowerError("Expected exactly one configured GPU instance")
        info = hits[0]
        if info.get("Region", config["COMP_REGION"]) != config["COMP_REGION"]:
            raise PowerError("Instance region mismatch")
        if info.get("Zone", config["COMP_ZONE"]) != config["COMP_ZONE"]:
            raise PowerError("Instance zone mismatch")
        return {"state": info.get("State", "Unknown"),
                "region": config["COMP_REGION"],
                "zone": config["COMP_ZONE"],
                "gpu_type": info.get("GpuType"),
                "gpu_count": info.get("GPU"),
                "charge_type": info.get("ChargeType"),
                "is_spot": bool(info.get("IsSpot", False))}
    except PowerError:
        raise
    except Exception:
        raise PowerError("Instance status request failed") from None


# One protected, locally tunneled Windows UE node — never a caller URL.
# The underlying provider control still addresses its pinned COMP_UHOST_ID.
UE_WORKER_POWER_URL = "http://127.0.0.1:18910/v7/power/readiness"
UE_WORKER_TOKEN_PATH = Path("/etc/director-ue-worker.token")
UE_WORKER_NODE_ID = "ue-worker-01"
UE_POWER_STOP_GUARD_VERSION = "ue_worker_tasklist_v1"
UE_READINESS_MAX_BYTES = 4096


class NoPowerRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise PowerError("ue_readiness_redirect_denied")


def get_queue_state(config: dict, opener=None, token_file=None) -> dict:
    """Return a *UE Worker* verified workload gate for power-off.

    Retains the historic function name only for internal build_plan callers.
    ComfyUI/H3 is NOT queried and may NOT authorize a UE instance stop.
    Unavailable tunnel, unverifiable process list or stale data fail closed.
    """
    if token_file is not None:
        path = Path(token_file)
    elif os.environ.get("CREDENTIALS_DIRECTORY"):
        # Read systemd's private LoadCredential copy of the root-owned token.
        path = Path(os.environ["CREDENTIALS_DIRECTORY"]) / "ueworkertoken"
    else:
        path = UE_WORKER_TOKEN_PATH
    try:
        if path.is_symlink() or not path.is_file():
            raise PowerError("ue_worker_token_unavailable")
        info = path.stat()
        if info.st_size > 128 or info.st_size < 64 or (
                stat.S_IMODE(info.st_mode) & 0o007):
            raise PowerError("ue_worker_token_unavailable")
        token = path.read_text("ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            raise PowerError("ue_worker_token_invalid")
        req = urllib.request.Request(
            UE_WORKER_POWER_URL, method="GET",
            headers={"Accept": "application/json",
                     "Authorization": "Bearer " + token,
                     "Cache-Control": "no-store"},
        )
        request_open = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoPowerRedirect()).open
        with request_open(req, timeout=8) as response:
            if response.geturl() != UE_WORKER_POWER_URL:
                raise PowerError("ue_worker_readiness_redirected")
            if getattr(response, "status", 200) != 200:
                raise PowerError("ue_worker_readiness_not_verified")
            content = response.read(UE_READINESS_MAX_BYTES + 1)
        if len(content) > UE_READINESS_MAX_BYTES:
            raise PowerError("ue_worker_readiness_too_large")
        import json
        data = json.loads(content)
        if (type(data) is not dict or data.get("ok") is not True or
            data.get("verified") is not True or
            data.get("process_inventory_verified") is not True or
            data.get("kind") != "director_ue_windows_power_readiness_v1" or
            data.get("node_id") != UE_WORKER_NODE_ID or
            data.get("platform") != "Windows"):
            raise PowerError("ue_worker_readiness_not_verified")
        processes = data.get("unreal_process_count")
        job = data.get("active_job_id")
        if (type(processes) is not int or processes < 0 or processes > 65535
                or (job is not None and
                    (type(job) is not str or not re.fullmatch(r"[a-f0-9]{32}",job)))
                or type(data.get("safe_to_stop")) is not bool
                or data["safe_to_stop"] != (processes == 0 and job is None)):
            raise PowerError("ue_worker_readiness_invalid")
        from datetime import datetime, timezone
        checked = datetime.fromisoformat(data["checked_at"])
        if (checked.tzinfo is None or
                abs((datetime.now(timezone.utc) - checked).total_seconds()) > 30):
            raise PowerError("ue_worker_readiness_stale")
        busy = processes > 0 or job is not None
        return {"verified": True, "empty": not busy,
                "running": processes + int(job is not None),
                "pending": 0, "source": "ue_worker",
                "node_id": UE_WORKER_NODE_ID}
    except (PowerError, OSError, ValueError, UnicodeError, TypeError,
            KeyError, urllib.error.URLError):
        return {"verified": False, "reason": "ue_worker_readiness_not_verified"}



def evaluate_action(action: str, state: dict, queue: dict | None) -> dict:
    if action not in VALID_ACTIONS:
        raise PowerError("Unsupported operation")
    current = state["state"]
    needed = "Stopped" if action == "start" else "Running"
    if current != needed:
        return {"allowed": False, "action": action, "state": current,
                "reason": "instance_state_not_" + needed.lower()}
    if action == "stop":
        if state.get("is_spot"):
            return {"allowed": False, "action": action, "state": current,
                    "reason": "spot_instance_manual_stop_not_supported"}
        if (not queue or queue.get("verified") is not True
                or queue.get("source") != "ue_worker"):
            return {"allowed": False, "action": action, "state": current,
                    "reason": "ue_worker_readiness_not_verified"}
        if (queue.get("empty") is not True or
                type(queue.get("running")) is not int or
                type(queue.get("pending")) is not int or
                queue["running"] != 0 or queue["pending"] != 0):
            return {"allowed": False, "action": action, "state": current,
                    "reason": "ue_worker_busy",
                    "running": queue.get("running"),
                    "pending": queue.get("pending")}
    return {"allowed": True, "action": action, "state": current,
            "ue_workload_verified": bool(queue and queue.get("verified")),
            "message": "Approved for local interactive confirmation; NOT executed"}


def build_plan(action: str, config: dict, client=None, queue_check=get_queue_state) -> dict:
    state = get_provider_state(config, client)
    queue = queue_check(config) if action == "stop" and state["state"] == "Running" else None
    decision = evaluate_action(action, state, queue)
    # No instance ID, secrets, queue URL or raw provider response.
    return {"instance": {"gpu_type": state.get("gpu_type"),
                         "region": state["region"], "zone": state["zone"],
                         "charge_type": state.get("charge_type"),
                         "state": state["state"]},
            "workload": queue, **decision}


def submit_power_request(action: str, config: dict, client=None) -> dict:
    silence_sdk_logging()
    if action not in VALID_ACTIONS:
        raise PowerError("Unsupported operation")
    client = client or create_provider_client(config)
    name = {"start": "StartCompShareInstance",
            "stop": "StopCompShareInstance"}[action]
    try:
        response = client.ucompshare().invoke(name, {
            "Region": config["COMP_REGION"],
            "Zone": config["COMP_ZONE"],
            "UHostId": config["COMP_UHOST_ID"],
        })
        if not isinstance(response, dict) or response.get("RetCode") != 0:
            raise PowerError("Power operation rejected by provider")
    except PowerError:
        raise
    except Exception:
        raise PowerError("Power operation request failed") from None
    # Accepted by the API is NOT proof the GPU has already finished powering on/off.
    return {"accepted": True, "operation": action,
            "instance_final_state": "not_yet_verified"}
