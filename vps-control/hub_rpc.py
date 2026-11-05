"""Director Hub V0.6: strict, local-only routing to GPU and unified VPS core.

The Hub has no direct cloud provider credentials and NO power execution tool.
All start/stop requests remain behind the existing mobile biometric approval.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from hub_brain import call_studio

GPU_TOOLS = frozenset({
    "get_studio_status", "get_queue_summary", "list_h3_nodes",
    "list_h3_workflows", "get_h3_workflow_structure",
    "audit_h3_workflow", "get_h3_node_inputs", "get_upgrade_readiness",
})
VPS_TOOLS = frozenset({"get_control_center_status", "get_gpu_power_status"})
POWER_TOOLS = frozenset({
    "request_gpu_start", "request_gpu_stop", "get_power_request_status",
})
BRAIN_READ_TOOLS = frozenset({"get_production_dashboard","get_production_episode"})
BRAIN_WRITE_TOOLS = frozenset({
    "create_production_project","create_production_episode",
    "add_production_shot","save_production_outline",
})
BRAIN_TOOLS = BRAIN_READ_TOOLS | BRAIN_WRITE_TOOLS
ALL_TOOLS = GPU_TOOLS | VPS_TOOLS | POWER_TOOLS | BRAIN_TOOLS

GPU_PORT = 18790  # SSH -R endpoint, VPS LOOPBACK ONLY.
VPS_PORT = 8892  # Unified private VPS state + staged request service
POWER_PORT = 8892
MAX_REPLY = 1_048_576
MAX_PARAMS = 16_384
MAX_NODE_NAME = 160
PATH_PATTERN = re.compile(r"^/mcp/[a-zA-Z0-9_-]{40,160}$")


class HubError(ValueError):
    pass


def gpu_path(path_file=None):
    """Read only the private MCP route path, NEVER the provider credential file."""
    source = Path(path_file or os.environ.get(
        "DIRECTOR_HUB_GPU_PATH_FILE", "/etc/comfyui-director-hub-gpu-path"))
    if source.is_symlink() or not source.is_file():
        raise HubError("gpu_route_unconfigured")
    if source.stat().st_size > 200:
        raise HubError("gpu_route_invalid")
    value = source.read_text(encoding="ascii").strip()
    if not PATH_PATTERN.fullmatch(value):
        raise HubError("gpu_route_invalid")
    return value


def endpoint(tool, path_file=None):
    """Hardcoded service selection; callers cannot provide an upstream URL."""
    if tool in GPU_TOOLS:
        return "http://127.0.0.1:" + str(GPU_PORT) + gpu_path(path_file)
    if tool in VPS_TOOLS:
        return "http://127.0.0.1:" + str(VPS_PORT) + "/mcp"
    if tool in POWER_TOOLS:
        return "http://127.0.0.1:" + str(POWER_PORT) + "/mcp"
    if tool in BRAIN_TOOLS:
        return "http://127.0.0.1:8900/api/v1/brain"
    raise HubError("tool_not_allowlisted")


def check_args(tool, params):
    if tool not in ALL_TOOLS:
        raise HubError("tool_not_allowlisted")
    if not isinstance(params, dict):
        raise HubError("invalid_arguments")
    if tool in BRAIN_TOOLS:
        fields={
            "get_production_dashboard":(),
            "get_production_episode":("project_id","episode_id"),
            "create_production_project":("project_id","title"),
            "create_production_episode":("project_id","episode_id","title","ordinal"),
            "add_production_shot":(
                "project_id","episode_id","shot_id","ordinal","duration_ms"),
            "save_production_outline":(
                "project_id","episode_id","body","expected_revision"),
        }
        if set(params)!=set(fields[tool]):
            raise HubError("unexpected_arguments")
        for name,value in params.items():
            if name in ("ordinal","duration_ms","expected_revision"):
                if type(value) is not int:
                    raise HubError("invalid_argument_value")
                if (name=="ordinal" and not 1<=value<=10000 or
                        name=="duration_ms" and not 1<=value<=120000 or
                        name=="expected_revision" and not 0<=value<=100):
                    raise HubError("invalid_argument_value")
            elif not isinstance(value,str):
                raise HubError("invalid_argument_value")
            elif name=="body":
                if not value.strip() or len(value)>12000 or "\x00" in value:
                    raise HubError("invalid_argument_value")
            elif name=="title":
                if not value.strip() or len(value)>160 or any(
                        ord(ch)<32 for ch in value):
                    raise HubError("invalid_argument_value")
            elif name=="shot_id":
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}",value):
                    raise HubError("invalid_argument_value")
            elif not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,47}",value):
                raise HubError("invalid_argument_value")
        return dict(params)
    required = {
        "get_h3_workflow_structure": "name",
        "audit_h3_workflow": "name",
        "get_h3_node_inputs": "node_type",
        "get_power_request_status": "request_id",
    }
    if tool not in required:
        if params:
            raise HubError("unexpected_arguments")
        return {}
    field = required[tool]
    if set(params) != {field}:
        raise HubError("unexpected_arguments")
    value = params.get(field)
    if (not isinstance(value, str) or not 1 <= len(value) <= MAX_NODE_NAME
            or any(ord(ch) < 32 for ch in value)):
        raise HubError("invalid_argument_value")
    if tool == "get_power_request_status" and not re.fullmatch(
        r"[A-Za-z0-9_-]{20,80}", value
    ):
        raise HubError("invalid_request_id")
    return {field: value}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HubError("backend_redirect_blocked")


_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _NoRedirect()
)


def unwrap(value):
    if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
        raise HubError("upstream_invalid_jsonrpc")
    if "error" in value:
        raise HubError("upstream_tool_error")
    response = value.get("result")
    if not isinstance(response, dict) or response.get("isError") is True:
        raise HubError("upstream_tool_error")
    structured = response.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for item in response.get("content", []):
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        try:
            data = json.loads(item.get("text", ""))
            if isinstance(data, dict):
                return data
        except (TypeError, ValueError):
            pass
    raise HubError("upstream_result_unrecognized")


def call(tool, params=None, path_file=None, opener=None):
    """Proxy one known MCP tool to a pinned local backend; sanitized errors only."""
    if params is None:
        params = {}
    try:
        validated = check_args(tool, params)
        if tool in BRAIN_TOOLS:
            # Keep Studio credential out of the 13 legacy GPU/VPS routes.
            return call_studio(tool,validated)
        url = endpoint(tool, path_file)
        body = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": validated},
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_PARAMS:
            raise HubError("request_too_large")
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream",
                     "Mcp-Protocol-Version": "2025-03-26",
                     "Host": "127.0.0.1:" + str(
                         8790 if tool in GPU_TOOLS else
                         VPS_PORT if tool in VPS_TOOLS else POWER_PORT)},
        )
        backend = opener or _OPENER
        with backend.open(request, timeout=15) as stream:
            if stream.geturl() != url:
                raise HubError("backend_redirect_blocked")
            payload = stream.read(MAX_REPLY + 1)
            if len(payload) > MAX_REPLY:
                raise HubError("upstream_response_too_large")
        data = unwrap(json.loads(payload))
        # The backends redact privileged values. Never forward raw HTTP errors
        # or network exceptions, which may include private MCP paths.
        return data
    except HubError as exc:
        return {"ok": False, "reason": str(exc)}
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return {"ok": False, "reason": "backend_unavailable"}
