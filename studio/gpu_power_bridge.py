"""Owner-only Studio -> local VPS power MCP bridge.

No arbitrary HTTP target or MCP tool name is accepted. The Studio HTTP route
must independently enforce Microsoft-owner session, HTTPS proxy, Origin and
CSRF. The private power core stays loopback-only on 127.0.0.1:8892.
"""
from __future__ import annotations

import json
import urllib.request

CORE = "http://127.0.0.1:8892/mcp"
ALLOWED = {"start": "start_gpu_now", "stop": "stop_gpu_now"}
MAX_RESPONSE = 16384
FIELDS = ("ok", "request_id", "action", "state", "result", "reason",
          "approval_required", "final_state_verified")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("power_backend_redirect_denied")


_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _NoRedirect())


def operate(action: str, opener=None) -> dict:
    if type(action) is not str or action not in ALLOWED:
        return {"ok": False, "reason": "invalid_power_action"}
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": ALLOWED[action], "arguments": {}},
    }, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        CORE, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Protocol-Version": "2025-03-26",
            "Host": "127.0.0.1:8892",
        })
    try:
        with (opener or _OPENER).open(req, timeout=22) as response:
            if response.geturl() != CORE:
                return {"ok": False, "reason": "power_backend_redirect_denied"}
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            return {"ok": False, "reason": "power_backend_response_too_large"}
        envelope = json.loads(raw)
        if (not isinstance(envelope, dict) or envelope.get("jsonrpc") != "2.0"
                or "error" in envelope):
            return {"ok": False, "reason": "power_backend_protocol_error"}
        payload = envelope.get("result")
        if not isinstance(payload, dict) or payload.get("isError"):
            return {"ok": False, "reason": "power_backend_tool_error"}
        value = payload.get("structuredContent")
        if not isinstance(value, dict):
            for part in payload.get("content", []):
                if isinstance(part, dict) and part.get("type") == "text":
                    try:
                        value = json.loads(part.get("text", ""))
                    except (ValueError, TypeError):
                        pass
                    if isinstance(value, dict):
                        break
        if not isinstance(value, dict) or type(value.get("ok")) is not bool:
            return {"ok": False, "reason": "power_backend_result_invalid"}
        return {name: value[name] for name in FIELDS if name in value}
    except Exception:
        return {"ok": False, "reason": "power_backend_unavailable"}
