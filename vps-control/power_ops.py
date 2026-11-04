"""Local-only CompShare GPU power controller. NEVER expose this module as an anonymous MCP tool.

Read-only inspection can be reused by an authenticated MCP API later.
Actual start/stop is invoked only by powerctl.py with local interactive confirmation.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

VALID_ACTIONS = {"start", "stop"}
ENV_KEYS = {"COMP_PUBLIC_KEY", "COMP_PRIVATE_KEY", "COMP_UHOST_ID",
            "COMP_REGION", "COMP_ZONE", "DIRECTOR_GPU_QUEUE_URL",
            "DIRECTOR_GPU_QUEUE_BEARER"}
QUEUE_LIMIT_BYTES = 65536

class PowerError(Exception):
    """Safe failure; the message never includes provider response or credentials."""


def read_env_file(path: str = "/etc/comfyui-director-control.env") -> dict:
    file = Path(path)
    mode = stat.S_IMODE(file.stat().st_mode)
    if mode & 0o077:
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


def create_provider_client(config: dict):
    from ucloud.client import Client
    return Client({
        "region": config["COMP_REGION"],
        "public_key": config["COMP_PUBLIC_KEY"],
        "private_key": config["COMP_PRIVATE_KEY"],
        "base_url": "https://api.compshare.cn",
    })


def get_provider_state(config: dict, client=None) -> dict:
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
                "charge_type": info.get("ChargeType"),
                "is_spot": bool(info.get("IsSpot", False))}
    except PowerError:
        raise
    except Exception:
        raise PowerError("Instance status request failed") from None


def get_queue_state(config: dict, opener=urlopen) -> dict:
    url = config.get("DIRECTOR_GPU_QUEUE_URL", "")
    if not url:
        return {"verified": False, "reason": "queue_url_not_configured"}
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return {"verified": False, "reason": "queue_endpoint_must_use_https"}
    if parsed.fragment:
        return {"verified": False, "reason": "queue_endpoint_invalid"}
    headers = {"Accept": "application/json"}
    if config.get("DIRECTOR_GPU_QUEUE_BEARER"):
        headers["Authorization"] = "Bearer " + config["DIRECTOR_GPU_QUEUE_BEARER"]
    try:
        req = Request(url, headers=headers, method="GET")
        with opener(req, timeout=8) as response:
            final_url = urlparse(response.geturl())
            if final_url.scheme != "https" or final_url.hostname != parsed.hostname:
                return {"verified": False, "reason": "queue_endpoint_redirected"}
            data = response.read(QUEUE_LIMIT_BYTES + 1)
        if len(data) > QUEUE_LIMIT_BYTES:
            return {"verified": False, "reason": "queue_response_too_large"}
        import json
        payload = json.loads(data)
        running, pending = payload["queue_running"], payload["queue_pending"]
        if not isinstance(running, list) or not isinstance(pending, list):
            raise TypeError("Invalid queue")
        return {"verified": True, "running": len(running), "pending": len(pending),
                "empty": not running and not pending}
    except Exception:
        return {"verified": False, "reason": "queue_unreachable_or_invalid"}


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
        if not queue or not queue.get("verified"):
            return {"allowed": False, "action": action, "state": current,
                    "reason": "comfyui_queue_not_verified"}
        if not queue.get("empty"):
            return {"allowed": False, "action": action, "state": current,
                    "reason": "comfyui_queue_not_empty",
                    "running": queue.get("running"),
                    "pending": queue.get("pending")}
    return {"allowed": True, "action": action, "state": current,
            "queue_verified": bool(queue and queue.get("verified")),
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
            "queue": queue, **decision}


def submit_power_request(action: str, config: dict, client=None) -> dict:
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
