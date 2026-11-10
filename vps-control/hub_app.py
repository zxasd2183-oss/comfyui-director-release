"""ChatGPT-facing Director Hub: GPU/VPS/power plus authenticated Studio brain tools.

The Hub has no cloud provider credentials. Its authenticated private bridge
can call protected VPS immediate GPU power tools without per-action approval.
"""
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from hub_rpc import call
from hub_file_sync import sync_chatgpt_visual
from hub_sync_jobs import JOBS
from ue_worker_rpc import (call_ue_worker,
                           enqueue_ue_episode_timeline as enqueue_ue_episode_timeline_rpc,
                           get_ue_episode_job_status as get_ue_episode_job_status_rpc)

app = FastMCP("Director Hub Studio Brain", host="127.0.0.1", port=8898,
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
    """Read actual GPU instance power state from the unified VPS core."""
    return call("get_gpu_power_status")


@app.tool(annotations=WRITE)
def start_gpu_now() -> dict:
    """Start the GPU immediately through the protected VPS core.

    No separate TOTP or biometric approval. GPU billing may begin.
    Returns provider submission state; verify actual Running state separately.
    """
    return call("start_gpu_now")


@app.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                      idempotentHint=False, openWorldHint=False))
def stop_gpu_now() -> dict:
    """Stop GPU immediately only when its ComfyUI queue is verified empty.

    Confirm that generated results are already saved to persistent storage.
    No separate phone/browser approval.
    """
    return call("stop_gpu_now")


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



# Creator-facing tools: read project context; write only audited project
# metadata, storyboard-shot metadata and episode outline DRAFTS in Studio.
# These do not run any GPU, external provider action or artistic approval.
@app.tool(annotations=READ)
def get_production_dashboard() -> dict:
    """Read Director Studio project and episode summaries, counts and audit status."""
    return call("get_production_dashboard")


@app.tool(annotations=READ)
def get_production_episode(project_id: str, episode_id: str) -> dict:
    """Read one private Studio episode with registered shots, assets and outline draft."""
    return call("get_production_episode", {
        "project_id":project_id,"episode_id":episode_id,
    })


@app.tool(annotations=WRITE)
def create_production_project(project_id: str, title: str) -> dict:
    """Create a new audited Studio project; never starts GPU jobs."""
    return call("create_production_project", {
        "project_id":project_id,"title":title,
    })


@app.tool(annotations=WRITE)
def create_production_episode(
    project_id: str, episode_id: str, title: str, ordinal: int,
) -> dict:
    """Add an episode to a Studio project with an audited creation record."""
    return call("create_production_episode", {
        "project_id":project_id,"episode_id":episode_id,
        "title":title,"ordinal":ordinal,
    })


@app.tool(annotations=WRITE)
def add_production_shot(
    project_id: str, episode_id: str, shot_id: str,
    ordinal: int, duration_ms: int,
) -> dict:
    """Record one planned storyboard shot's ID, order and duration; no rendering."""
    return call("add_production_shot", {
        "project_id":project_id,"episode_id":episode_id,"shot_id":shot_id,
        "ordinal":ordinal,"duration_ms":duration_ms,
    })


@app.tool(annotations=WRITE)
def save_production_outline(
    project_id: str, episode_id: str, body: str, expected_revision: int,
) -> dict:
    """Save a versioned DRAFT episode creative outline; use revision 0 initially."""
    return call("save_production_outline", {
        "project_id":project_id,"episode_id":episode_id,
        "body":body,"expected_revision":expected_revision,
    })


# Project-wide reusable characters: no GPU actions and NO artistic approval.
# Existing episode images remain immutable. A human director approves masters.
@app.tool(annotations=READ)
def get_project_characters(project_id: str) -> dict:
    """Read reusable project characters, candidate media links and master-review state."""
    return call("get_project_characters", {"project_id":project_id})


@app.tool(annotations=WRITE)
def create_project_character(
    project_id: str, character_id: str, display_name: str, role: str,
    brand_basis: str, design_language: str, character_notes: str,
) -> dict:
    """Add one DRAFT character profile with original brand-inspired design, never a logo."""
    return call("create_project_character", {
        "project_id":project_id,"character_id":character_id,
        "display_name":display_name,"role":role,"brand_basis":brand_basis,
        "design_language":design_language,"character_notes":character_notes,
    })


@app.tool(annotations=WRITE)
def update_project_character(
    project_id: str, character_id: str, expected_revision: int,
    display_name: str, role: str, brand_basis: str,
    design_language: str, character_notes: str,
) -> dict:
    """Edit one draft character profile only with revision check; does not approve a master."""
    return call("update_project_character", {
        "project_id":project_id,"character_id":character_id,
        "expected_revision":expected_revision,"display_name":display_name,
        "role":role,"brand_basis":brand_basis,
        "design_language":design_language,"character_notes":character_notes,
    })


@app.tool(annotations=WRITE)
def link_project_character_visual(
    project_id: str, character_id: str, visual_id: str, reference_type: str,
) -> dict:
    """Link an existing character visual candidate without copying media or approving it."""
    return call("link_project_character_visual", {
        "project_id":project_id,"character_id":character_id,
        "visual_id":visual_id,"reference_type":reference_type,
    })


class ChatGPTFileRef(BaseModel):
    download_url: str
    file_id: str
    mime_type: str | None = None
    file_name: str | None = None


@app.tool(annotations=WRITE,meta={"openai/fileParams":["file"]})
def sync_chatgpt_visual_to_studio(
    project_id: str, episode_id: str, kind: str, subject_id: str,
    file: ChatGPTFileRef,
) -> dict:
    """Sync one authorized ChatGPT image immediately into a specific Studio episode.

    Supports role images (kind=character), scene references (kind=scene) and
    storyboard frames (kind=storyboard). No manual download, no GPU and no
    changes to the original project outline. The host supplies a temporary
    authorized file reference; do not invent a download URL.
    """
    return sync_chatgpt_visual(project_id,episode_id,kind,subject_id,
                               file.model_dump(exclude_none=True))


@app.tool(annotations=WRITE,meta={"openai/fileParams":["file"]})
def enqueue_chatgpt_visual_to_studio(
    project_id: str, episode_id: str, kind: str, subject_id: str,
    file: ChatGPTFileRef,
) -> dict:
    """Start an authorized image transfer and return its job ID immediately.

    For large files, use this instead of the synchronous visual sync tool.
    Poll get_chatgpt_visual_sync_status for a committed Studio visual ID.
    Signed file URLs are never written to disk or included in status records.
    """
    return JOBS.submit(project_id,episode_id,kind,subject_id,
                       file.model_dump(exclude_none=True))


@app.tool(annotations=READ)
def get_chatgpt_visual_sync_status(job_id: str) -> dict:
    """Read completion of a previous ChatGPT image transfer, without GPU actions."""
    return JOBS.status(job_id)


@app.tool(annotations=READ)
def list_recent_chatgpt_visual_syncs(project_id: str, episode_id: str) -> dict:
    """Recover recent image-transfer receipts even if an MCP response was lost.

    Volatile receipts expire after one hour or Hub service restart. Always
    check Studio's persisted episode visual list for final confirmation.
    """
    return JOBS.recent(project_id,episode_id)


# Windows UE node control is independent of the retired H3 GPU.
# This adapter is disabled until the private shared secret and tunnel are installed.
@app.tool(annotations=READ)
def get_ue_worker_status() -> dict:
    """Read authenticated Windows UE node/GPU/engine health over the private tunnel."""
    return call_ue_worker("get_ue_worker_status")


@app.tool(annotations=READ)
def get_ue_worker_capabilities() -> dict:
    """Read the UE worker's explicit allowlist of supported operations."""
    return call_ue_worker("get_ue_worker_capabilities")


@app.tool(annotations=WRITE)
def prepare_ue_workspace() -> dict:
    """Create only the predefined UE project folders on the Windows worker.

    No arbitrary shell, script execution, program installation or rendering.
    """
    return call_ue_worker("prepare_ue_workspace")



@app.tool(annotations=WRITE)
def enqueue_ue_episode_timeline(project_id: str, episode_id: str) -> dict:
    """Start the real Unreal Editor headless build of Studio's episode timeline.

    Loads the registered ordered shots from Director Studio (no caller-supplied
    scripts or commands). Starts Unreal Editor on the metered Windows GPU;
    returns a job ID, not an assertion of successful asset production.
    """
    return enqueue_ue_episode_timeline_rpc(project_id, episode_id)


@app.tool(annotations=READ)
def get_ue_episode_job_status(job_id: str) -> dict:
    """Read actual UE Editor timeline job state and result by bounded ID."""
    return get_ue_episode_job_status_rpc(job_id)


if __name__ == "__main__":
    app.run(transport="streamable-http")
