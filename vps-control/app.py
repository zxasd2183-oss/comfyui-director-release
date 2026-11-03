"""Ubuntu VPS read-only MCP control center.

Always binds to localhost; do not expose via a public tunnel without OAuth.
"""
import os
from mcp.server.fastmcp import FastMCP
from api import config_status, get_instance_status

PORT = int(os.getenv('DIRECTOR_VPS_PORT', '8890'))
service = FastMCP(
    'ComfyUI Director VPS Control',
    host='127.0.0.1',
    port=PORT,
    stateless_http=True,
    json_response=True,
)

@service.tool()
def get_control_center_status() -> dict:
    """Read-only: check whether the always-on VPS controller is configured."""
    return config_status()

@service.tool()
def get_gpu_power_status() -> dict:
    """Read-only: get the current power state of the selected CompShare GPU."""
    return get_instance_status()

if __name__ == '__main__':
    service.run(transport='streamable-http')
