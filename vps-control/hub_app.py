"""Single ChatGPT-facing Director Hub V0.5: 8 GPU + 2 VPS + 3 power tools.

The Hub NEVER invokes provider Start/Stop APIs. The existing Power Requests
service creates pending requests, and Jipite's biometric approval remains the
only normal path that authorizes a real provider operation.
"""
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from hub_rpc import call

app = FastMCP("Director Hub V0.5", host="127.0.0.1", port=8896,
              stateless_http=True, json_response=True)

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                        idempotentHint=False, openWorldHint=False)


@app.tool(annotations=READ)
def get_studio_status() -> dict:
    """Read GPU ComfyUI version, available VRAM and queue counters."""
    return call("get_studio_status")


@app.tool(annotations=READ)
def get_queue_summary() -> dict:
    """Read pending/running ComfyUI queue counts without changing the queue."""
    return call("get_queue_summary")


@app.tool(annotations=READ)
def list_h3_nodes() -> dict:
    """List installed MiniMax H3 node types from the GPU."""
    return call("list_h3_nodes")


@app.tool(annotations=READ)
def list_h3_workflows() -> dict:
    """List saved MiniMax H3 workflows with prompts redacted."""
    return call("list_h3_workflows")


@app.tool(annotations=READ)
def get_h3_workflow_structure(name: str) -> dict:
    """Read approved H3 workflow structure and nested subgraph mappings."""
    return call("get_h3_workflow_structure", {"name": name})


@app.tool(annotations=READ)
def audit_h3_workflow(name: str) -> dict:
    """Audit an H3 workflow's connections; never executes generation."""
    return call("audit_h3_workflow", {"name": name})


@app.tool(annotations=READ)
def get_h3_node_inputs(node_type: str) -> dict:
    """Read installed H3 node field types, not model weights or secrets."""
    return call("get_h3_node_inputs", {"node_type": node_type})


@app.tool(annotations=READ)
def get_upgrade_readiness() -> dict:
    """Inspect the installed GPU Director version and signed-update readiness."""
    return call("get_upgrade_readiness")


@app.tool(annotations=READ)
def get_control_center_status() -> dict:
    """Read the always-on VPS controller health/configuration status."""
    return call("get_control_center_status")


@app.tool(annotations=READ)
def get_gpu_power_status() -> dict:
    """Read actual GPU instance power state from the VPS controller."""
    return call("get_gpu_power_status")


@app.tool(annotations=WRITE)
def request_gpu_start() -> dict:
    """CREATE a GPU start request ONLY. The phone owner must approve in Jipite
    with biometric signing before a provider action. May begin GPU billing.
    """
    return call("request_gpu_start")


@app.tool(annotations=WRITE)
def request_gpu_stop() -> dict:
    """CREATE a GPU stop request ONLY; refuse if queue cannot be verified.
    The phone owner must approve in Jipite. Verify files are persisted first.
    """
    return call("request_gpu_stop")


@app.tool(annotations=READ)
def get_power_request_status(request_id: str) -> dict:
    """Read the state of an existing start/stop approval request."""
    return call("get_power_request_status", {"request_id": request_id})


if __name__ == "__main__":
    app.run(transport="streamable-http")
