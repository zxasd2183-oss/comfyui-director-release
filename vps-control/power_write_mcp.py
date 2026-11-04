"""Separate MCP for staged power requests. A MCP tool can NEVER itself power the GPU.

Authentication boundary: bind to localhost only; configure authenticated HTTPS
proxy separately. Requests require independent owner TOTP approval in browser.
"""
import os
import stat
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from power_ops import PowerError, read_env_file, read_systemd_credential_env
from power_v03 import DB_DEFAULT, plan_and_request, request_status

app = FastMCP("ComfyUI Director VPS - Power Requests",
              host="127.0.0.1", port=8892,
              stateless_http=True, json_response=True)

def _config():
    path = os.environ.get("DIRECTOR_POWER_CONFIG")
    if not path:
        directory = os.environ.get("CREDENTIALS_DIRECTORY")
        if directory:
            path = os.path.join(directory, "directorenv")
    if not path:
        raise RuntimeError("Systemd LoadCredential path unavailable")
    if os.environ.get("CREDENTIALS_DIRECTORY"):
        return read_systemd_credential_env(path, os.environ["CREDENTIALS_DIRECTORY"])
    return read_env_file(path)

def _db():
    return os.environ.get("DIRECTOR_POWER_DB", DB_DEFAULT)

@app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def get_power_service_health() -> dict:
    """Safe diagnostic for V0.3 configuration; never returns credential values."""
    try:
        cfg = _config()
    except FileNotFoundError:
        return {"ok": False, "stage": "configuration", "reason": "credential_file_not_found"}
    except PermissionError:
        return {"ok": False, "stage": "configuration", "reason": "credential_file_access_denied"}
    except PowerError as exc:
        # PowerError messages from read_env_file are fixed strings or
        # required field NAMES; never include secret values.
        message = str(exc)
        if message.startswith("Credential file permissions"):
            reason = "credential_file_permissions_too_open"
        elif message.startswith("Power configuration incomplete:"):
            reason = "credential_required_fields_missing"
        elif message == "Invalid region":
            reason = "credential_region_invalid"
        elif message == "Invalid zone":
            reason = "credential_zone_invalid"
        elif message == "Original credential must be root-owned and mode 0600":
            reason = "original_credential_source_insecure"
        elif message.startswith("Systemd credential") or message.startswith("Unexpected runtime credential"):
            reason = "systemd_credential_path_invalid"
        elif message in ("Invalid config line", "Invalid config value"):
            reason = "credential_format_invalid"
        else:
            reason = "credential_file_invalid_or_incomplete"
        result = {"ok": False, "stage": "configuration", "reason": reason}
        if reason == "credential_file_permissions_too_open":
            try:
                credential_path = os.environ.get("DIRECTOR_POWER_CONFIG")
                directory = os.environ.get("CREDENTIALS_DIRECTORY")
                if not credential_path and directory:
                    credential_path = os.path.join(directory, "directorenv")
                if credential_path:
                    result["runtime_file_mode"] = format(stat.S_IMODE(os.stat(credential_path).st_mode), "04o")
                    result["loaded_via_systemd"] = bool(directory and os.path.realpath(credential_path).startswith(os.path.realpath(directory).rstrip("/") + "/"))
                    if directory:
                        result["credential_directory_mode"] = format(stat.S_IMODE(os.stat(directory).st_mode), "04o")
            except OSError:
                pass
        if reason == "credential_required_fields_missing":
            names = message.split(":", 1)[1].strip().split(", ")
            allowed = {"COMP_PUBLIC_KEY", "COMP_PRIVATE_KEY", "COMP_UHOST_ID",
                       "COMP_REGION", "COMP_ZONE"}
            result["missing_field_names"] = [name for name in names if name in allowed]
        return result
    except Exception:
        return {"ok": False, "stage": "configuration", "reason": "credential_read_unavailable"}
    try:
        from power_v03 import connect
        with connect(_db()) as db:
            db.execute("SELECT 1")
    except Exception:
        return {"ok": False, "stage": "database", "reason": "database_unavailable"}
    return {"ok": True, "stage": "ready", "config_loaded": True,
            "region_set": bool(cfg.get("COMP_REGION")),
            "zone_set": bool(cfg.get("COMP_ZONE")),
            "write_request_tools_enabled": True,
            "gpu_power_operation_executed": False}


@app.tool(annotations=ToolAnnotations(readOnlyHint=False,
                                      destructiveHint=False,
                                      idempotentHint=False,
                                      openWorldHint=False))
def request_gpu_start() -> dict:
    """Submit a GPU START application; DOES NOT start hardware.
    Your owner must separately approve in their 2FA browser page. May incur
    GPU billing only after that independent approval. Never guess approval codes.
    """
    try:
        return plan_and_request("start", _config(), _db())
    except Exception:
        return {"ok": False, "reason": "request_service_unavailable"}

@app.tool(annotations=ToolAnnotations(readOnlyHint=False,
                                      destructiveHint=False,
                                      idempotentHint=False,
                                      openWorldHint=False))
def request_gpu_stop() -> dict:
    """Submit a GPU STOP application; DOES NOT turn hardware off.
    Rejects when ComfyUI queue cannot be verified or is busy.
    Owner must separately check saved files and approve in 2FA browser.
    """
    try:
        return plan_and_request("stop", _config(), _db())
    except Exception:
        return {"ok": False, "reason": "request_service_unavailable"}

@app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def get_power_request_status(request_id: str) -> dict:
    """Check an existing application; does not change GPU power."""
    try:
        return request_status(request_id, _db())
    except Exception:
        return {"ok": False, "reason": "request_status_unavailable"}

if __name__ == "__main__":
    app.run(transport="streamable-http")
