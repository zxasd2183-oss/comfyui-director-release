"""V0.6 unified VPS status module, only used by the existing power MCP process.

Both public read-only status tools and staged power requests now share the same
systemd LoadCredential-protected provider config. No direct power operation
is exported here, and no provider response or secret value is returned.
"""
from __future__ import annotations

from power_ops import PowerError, get_provider_state


def control_center_status(config_fn):
    try:
        config = config_fn()
        valid = all(config.get(key) for key in (
            "COMP_PUBLIC_KEY", "COMP_PRIVATE_KEY", "COMP_UHOST_ID",
            "COMP_REGION", "COMP_ZONE"))
    except Exception:
        valid = False
    return {
        "version": "0.6.0",
        "configured": valid,
        "instance_selected": valid,
        "gpu_control_enabled": False,
        "mode": "read_only",
    }


def gpu_power_status(config_fn, state_fn=get_provider_state):
    try:
        config = config_fn()
    except Exception:
        return {"ok": False, "reason": "not_configured", "mode": "read_only"}
    try:
        status = state_fn(config)
        return {
            "ok": True,
            "state": status["state"],
            "region": status["region"],
            "zone": status["zone"],
            "gpu_type": status.get("gpu_type"),
            "gpu_count": status.get("gpu_count"),
            "charge_type": status.get("charge_type"),
            "is_spot": status.get("is_spot"),
            "mode": "read_only",
        }
    except (PowerError, Exception):
        # Only fixed reasons; never return raw SDK/provider errors.
        return {"ok": False, "reason": "provider_request_failed", "mode": "read_only"}
