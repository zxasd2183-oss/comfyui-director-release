#!/usr/bin/env python3
"""Safe local MCP check for the Guangzhou Ubuntu VPS read-only controller."""
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "http://127.0.0.1:8890/mcp"
EXPECTED = {"get_control_center_status", "get_gpu_power_status"}

async def main():
    print("Testing local Director VPS MCP on 127.0.0.1:8890 (no public network exposure).")
    async with streamablehttp_client(URL) as (reader, writer, _):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            listing = await session.list_tools()
            names = {tool.name for tool in listing.tools}
            missing = EXPECTED - names
            print("MCP tools:", sorted(names))
            if missing:
                print("FAIL: required tools missing", sorted(missing))
                return 2
            for tool in sorted(EXPECTED):
                result = await session.call_tool(tool)
                value = result.structuredContent
                if value is None:
                    for content in result.content:
                        if getattr(content, "type", "") == "text":
                            try:
                                value = json.loads(content.text)
                            except Exception:
                                value = {"ok": False, "reason": "unexpected_tool_format"}
                            break
                if not isinstance(value, dict):
                    print(tool, "FAIL: no structured data")
                    continue
                # Strong allowlist prevents emitting IDs, credentials, URLs and provider response.
                fields = (("version", "configured", "instance_selected", "gpu_control_enabled", "mode")
                          if tool == "get_control_center_status" else
                          ("ok", "reason", "state", "region", "zone", "gpu_type",
                           "gpu_count", "charge_type", "is_spot", "mode"))
                filtered = {k: value[k] for k in fields if k in value}
                print(tool + ":", json.dumps(filtered, ensure_ascii=False))
            print("Done. Never share the full /etc/comfyui-director-control.env file.")
            return 0

if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
        raise SystemExit(rc)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        print("FAIL: local MCP connection error:", type(exc).__name__)
        print("Check: sudo systemctl status director-vps-control --no-pager")
        raise SystemExit(1)
