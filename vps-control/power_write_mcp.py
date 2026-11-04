"""Separate MCP for staged power requests. A MCP tool can NEVER itself power the GPU.

Authentication boundary: bind to localhost only; configure authenticated HTTPS
proxy separately. Requests require independent owner TOTP approval in browser.
"""
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from power_ops import read_env_file
from power_v03 import DB_DEFAULT, plan_and_request, request_status

app = FastMCP("ComfyUI Director VPS - Power Requests",
              host="127.0.0.1", port=8892,
              stateless_http=True, json_response=True)

def _config():
    path = os.environ.get("DIRECTOR_POWER_CONFIG")
    if not path:
        raise RuntimeError("Systemd LoadCredential must supply DIRECTOR_POWER_CONFIG")
    return read_env_file(path)

def _db():
    return os.environ.get("DIRECTOR_POWER_DB", DB_DEFAULT)

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
