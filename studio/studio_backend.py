"""Read-only fixed local Hub MCP probes for the unprivileged Studio UI process.

No bearer secrets, no cloud SDK, no power action, no arbitrary tool names.
Public-facing Hub auth and all mobile power approvals remain independent.
"""
from __future__ import annotations
import json
import os
import urllib.request

TOOLS = frozenset({"get_gpu_power_status", "get_queue_summary"})
ALLOWED_PORTS = frozenset({8898, 8896})
MAX_REPLY = 65536

class BlockRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, url):
        raise ValueError("redirect_not_allowed")

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), BlockRedirect())


def query(name, *, port=None, opener=None):
    if name not in TOOLS:
        return {"ok": False, "reason": "read_only_tool_not_allowed"}
    try:
        actual_port = int(port or os.environ.get("DIRECTOR_STUDIO_HUB_PORT", "8898"))
        if actual_port not in ALLOWED_PORTS:
            return {"ok": False, "reason": "hub_port_not_allowed"}
        address = "http://127.0.0.1:" + str(actual_port) + "/mcp"
        body = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        }).encode("utf-8")
        req = urllib.request.Request(address, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Protocol-Version": "2025-03-26",
            "Host": "127.0.0.1:" + str(actual_port),
        })
        with (opener or OPENER).open(req, timeout=9) as res:
            if res.geturl() != address:
                raise ValueError("unexpected_redirect")
            raw = res.read(MAX_REPLY + 1)
        if len(raw) > MAX_REPLY:
            raise ValueError("oversized_response")
        data = json.loads(raw)
        if data.get("jsonrpc") != "2.0" or "error" in data:
            raise ValueError("mcp_error")
        result = data["result"]
        if result.get("isError"):
            raise ValueError("mcp_tool_error")
        status = result.get("structuredContent")
        if not isinstance(status, dict):
            text = [c.get("text") for c in result.get("content", [])
                    if isinstance(c, dict) and c.get("type") == "text"]
            status = json.loads(text[0]) if text else None
        if not isinstance(status, dict):
            raise ValueError("invalid_payload")
        # Exact response allowlist, not a generic serialization of backend data.
        if name == "get_gpu_power_status":
            if status.get("ok") is True:
                return {key: status.get(key) for key in (
                    "ok", "state", "gpu_type", "mode")}
            return {"ok": False, "reason": "gpu_power_unavailable"}
        if status.get("ok") is True:
            def count(preferred, alternative):
                result = status.get(preferred, status.get(alternative))
                return result if type(result) is int and 0 <= result < 100000 else None
            running, pending = count("running", "queue_running"), count("pending", "queue_pending")
            if running is not None and pending is not None:
                return {"ok": True, "running": running, "pending": pending}
        return {"ok": False, "reason": "comfy_queue_unavailable"}
    except Exception:
        return {"ok": False, "reason": "backend_unavailable"}
