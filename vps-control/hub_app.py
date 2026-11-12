"""ChatGPT-facing Director Hub: GPU/VPS/power plus authenticated Studio brain tools.

The Hub has no cloud provider credentials. Its authenticated private bridge
can call protected VPS immediate GPU power tools without per-action approval.
"""
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from hub_rpc import call
from hub_brain import call_studio
from hub_file_sync import sync_chatgpt_visual
from hub_sync_jobs import JOBS
from ue_worker_rpc import (call_ue_worker,
                           enqueue_ue_episode_timeline as enqueue_ue_episode_timeline_rpc,
                           enqueue_ue_stage_cameras as enqueue_ue_stage_cameras_rpc,
                           enqueue_ue_previs_stills as enqueue_ue_previs_stills_rpc,
                           enqueue_ue_asset_audit as enqueue_ue_asset_audit_rpc,
                           enqueue_ue_scene_candidates as enqueue_ue_scene_candidates_rpc,
                           enqueue_ue_cast_blueprints as enqueue_ue_cast_blueprints_rpc,
                           enqueue_ue_cast_review as enqueue_ue_cast_review_rpc,
                           get_ue_cast_review_png as get_ue_cast_review_png_rpc,
                           get_ue_episode_job_status as get_ue_episode_job_status_rpc,
                           get_ue_job_logs as get_ue_job_logs_rpc,
                           cancel_ue_job as cancel_ue_job_rpc,
                           get_ue_preview_png as get_ue_preview_png_rpc,
                           make_bounded_preview_thumbnail_png,
                           choose_mcp_preview_png,
                           get_ue_signed_update_status as get_ue_signed_update_status_rpc,
                           request_ue_signed_update as request_ue_signed_update_rpc)

UE_HUB_API_VERSION = "1.1.1"

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


# Studio already exposes scene, review and per-shot readiness data behind its
# own signed brain-link. These narrow, literal-argument methods go directly
# to the same HMAC-authenticated localhost endpoint. They never approve assets
# or dispatch any GPU job; legacy Hub routes and signed release allowlists stay
# unchanged.
@app.tool(annotations=READ)
def get_production_scenes(project_id: str) -> dict:
    """Read registered scene draft/approval status without copying private images."""
    return call_studio("get_production_scenes", {"project_id": project_id})


@app.tool(annotations=READ)
def get_production_episode_readiness(project_id: str, episode_id: str) -> dict:
    """Read per-shot real production blockers; never treat a plan as a rendered film."""
    return call_studio("get_production_episode_readiness",
                       {"project_id": project_id, "episode_id": episode_id})


@app.tool(annotations=WRITE)
def create_production_scene(
    project_id: str, scene_id: str, display_name: str, scene_type: str,
    layout_notes: str, lighting_notes: str, camera_rules: str,
    continuity_rules: str, scene_notes: str,
) -> dict:
    """Create one audited scene DRAFT; images and approval remain owner-reviewed."""
    return call_studio("create_production_scene", {
        "project_id": project_id, "scene_id": scene_id,
        "display_name": display_name, "scene_type": scene_type,
        "layout_notes": layout_notes, "lighting_notes": lighting_notes,
        "camera_rules": camera_rules, "continuity_rules": continuity_rules,
        "scene_notes": scene_notes,
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


@app.tool(annotations=READ)
def get_ue_episode_assembly_readiness() -> dict:
    """Inspect only EP01 final-assembly input filenames and WAV metadata.

    Read-only inventory; no shell, no ffprobe, no rendering, no Studio asset
    approval. Presence of inputs never asserts that clips or masters are valid.
    """
    return call_ue_worker("get_ue_episode_assembly_readiness")


@app.tool(annotations=WRITE)
def prepare_ue_workspace() -> dict:
    """Create only the predefined UE project folders on the Windows worker.

    No arbitrary shell, script execution, program installation or rendering.
    """
    return call_ue_worker("prepare_ue_workspace")



@app.tool(annotations=WRITE)
def prepare_ue_hero_metahuman_project() -> dict:
    """Create exactly one isolated UE 5.8 MetaHuman-enabled GPT hero project.

    No arbitrary paths, no downloads, no UE rendering and no changes to the
    existing EP01 31-shot world. This creates configuration, not a 3D master.
    """
    return call_ue_worker("prepare_ue_hero_metahuman_project")


@app.tool(annotations=WRITE)
def enqueue_ue_episode_timeline(project_id: str, episode_id: str) -> dict:
    """Start the real Unreal Editor headless build of Studio's episode timeline.

    Loads the registered ordered shots from Director Studio (no caller-supplied
    scripts or commands). Starts Unreal Editor on the metered Windows GPU;
    returns a job ID, not an assertion of successful asset production.
    """
    return enqueue_ue_episode_timeline_rpc(project_id, episode_id)


@app.tool(annotations=WRITE)
def enqueue_ue_stage_cameras(project_id: str, episode_id: str) -> dict:
    """Create a V03 non-destructive stage, 5 visibly marked proxy characters
    and 31 CineCameraActor shots based on Studio's frozen EP01 plan.

    Runs a fixed Unreal 5.8 script on the metered GPU. Existing V02
    timeline and approved production assets are never overwritten.
    """
    return enqueue_ue_stage_cameras_rpc(project_id, episode_id)


@app.tool(annotations=WRITE)
def enqueue_ue_previs_stills(project_id: str, episode_id: str) -> dict:
    """Render four 720x1280 PNG proof frames from the approved V03 stage.

    Fixed shots 01, 13, 26, 31; outputs verified PNG receipts (not MP4).
    Runs Unreal MRQ on a metered Windows GPU. No arbitrary inputs.
    """
    return enqueue_ue_previs_stills_rpc(project_id, episode_id)


@app.tool(annotations=WRITE)
def enqueue_ue_asset_audit(project_id: str, episode_id: str) -> dict:
    """Inventory native Unreal 5.8 assets for EP01's 5 characters, 2 scenes
    and 31 shot sequences. The Worker receives no arbitrary paths or scripts.

    Unreal Editor runs on the billed GPU; the audit never renders, approves
    drafts, replaces V03 assets, or mutates the UE project.
    """
    return enqueue_ue_asset_audit_rpc(project_id, episode_id)


@app.tool(annotations=WRITE)
def enqueue_ue_scene_candidates(project_id: str, episode_id: str) -> dict:
    """Build three editable, colored UE 5.8 environment drafts: office hall,
    the same hall's alarm-light variant, and glass-door entrance.

    Inputs come from locked Studio EP01 and its existing scene drafts, never
    from an arbitrary script/asset path. This starts billed UE Editor work.
    Only job-isolated Candidate assets are created; approved assets remain
    unchanged, and no character masters or video rendering are claimed.
    """
    return enqueue_ue_scene_candidates_rpc(project_id, episode_id)


@app.tool(annotations=WRITE)
def enqueue_ue_cast_blueprints(project_id: str, episode_id: str) -> dict:
    """Create 5 original, separately editable UE 5.8 cast-design Blueprint
    Actors with distinctive hair/clothes and Zero's RIGHT-hand red cord.

    Real billed Unreal Editor job; uses only the fixed Studio EP01 main cast
    list. No scripts, paths, face-identities, media, or user inputs forwarded.
    Actor Blueprints are NOT rigged skeletal MetaHumans or approved masters.
    """
    return enqueue_ue_cast_blueprints_rpc(project_id, episode_id)


@app.tool(annotations=WRITE)
def enqueue_ue_cast_review(project_id: str, episode_id: str) -> dict:
    """Render six REAL Unreal Engine 5.8 MRQ PNG views of the existing
    V1.0 five original character Blueprint assets, not mockups.

    One 1280x720 five-actor lineup plus five 720x1280 character portraits,
    bound to real CineCameraActors in a job-owned cloned review World.
    This runs paid Windows RTX4090 Unreal render operations and returns
    a job ID. Original level and approved masters stay unchanged.
    """
    return enqueue_ue_cast_review_rpc(project_id,episode_id)


@app.tool(annotations=READ)
def get_ue_episode_job_status(job_id: str) -> dict:
    """Read actual UE Editor timeline job state and result by bounded ID."""
    return get_ue_episode_job_status_rpc(job_id)


@app.tool(annotations=READ)
def get_ue_job_logs(job_id: str, kind: str) -> dict:
    """Read a small sanitized tail of one allowlisted log for a known UE job.

    kind: unreal, preset, render_01, render_13, render_26 or render_31.
    Does not accept file paths or serve arbitrary files.
    """
    return get_ue_job_logs_rpc(job_id, kind)


@app.tool(annotations=ToolAnnotations(readOnlyHint=False,
                                      destructiveHint=True, idempotentHint=True,
                                      openWorldHint=False))
def cancel_ue_job(job_id: str) -> dict:
    """Stop only the active job-owned Unreal process tree by job ID.

    Does not stop another user's process, choose a PID, or run shell commands.
    After requesting cancellation, poll get_ue_episode_job_status.
    """
    return cancel_ue_job_rpc(job_id)


@app.tool(annotations=READ)
def get_ue_preview_image(job_id: str, shot_id: str):
    """View an original PNG or a clearly declared size-limited derivative.

    The original 720x1280 PNG is always SHA-256-verified by the authenticated
    Windows Worker. For source PNGs <=512 KiB, returns original bytes.
    For larger sources, downscales IN MEMORY to a 360x640 (or 180x320)
    bridge-safe thumbnail; the real original PNG and receipt remain unchanged.
    This compatibility fallback also works in ChatGPT clients with an older
    cached tool list which cannot yet discover get_ue_preview_thumbnail.
    Existing 01/13/26/31 slots also show 4 genuine V1.1 cast review
    frames (LINEUP/GPT/DS/ZERO) when a completed cast-review job ID is used.
    No new render or arbitrary path.
    """
    # V1.1 backwards-compatible visual access in already-connected chat
    # sessions whose cached 50-tool interface predates cast review images.
    # This only maps four known V0.4 shot slots for a completed CAST job;
    # other job types retain their original strict V0.4 stage preview path.
    status = get_ue_episode_job_status_rpc(job_id)
    if (status.get("ok") and status.get("task")=="render_cast_review_stills"):
        mapping={"01":"LINEUP","13":"GPT","26":"DS","31":"ZERO"}
        if shot_id not in mapping:
            return {"ok":False,"reason":"invalid_cast_review_compat_slot"}
        result=get_ue_cast_review_png_rpc(job_id,mapping[shot_id])
    else:
        result = get_ue_preview_png_rpc(job_id, shot_id)
    if not result.get("ok"):
        return {"ok": False, "reason": result.get("reason", "preview_unavailable")}
    try:
        data = choose_mcp_preview_png(result["data"])
    except (RuntimeError, ValueError, TypeError, OSError):
        return {"ok": False, "reason": "preview_image_transport_unavailable"}
    return Image(data=data, format="png")


@app.tool(annotations=READ)
def get_ue_preview_thumbnail(job_id: str, shot_id: str):
    """View a verified UE PNG as a bounded 360x640/180x320 PNG thumbnail.

    Original 720x1280 PNG is independently verified by the Windows
    Worker SHA-256 receipt over the private SSH tunnel, but may exceed the
    fixed 1MiB MCP JSON bridge after Base64 encoding. This is explicitly
    a *viewing derivative*; it never alters or replaces the source PNG,
    receipt, source Unreal asset or render job. Shots: 01, 13, 26, 31.
    """
    result = get_ue_preview_png_rpc(job_id, shot_id)
    if not result.get("ok"):
        return {"ok": False, "reason": result.get("reason", "preview_unavailable")}
    try:
        thumb = make_bounded_preview_thumbnail_png(result["data"])
    except (RuntimeError, ValueError, TypeError, OSError):
        return {"ok": False, "reason": "preview_thumbnail_unavailable"}
    return Image(data=thumb, format="png")


@app.tool(annotations=READ)
def get_ue_cast_review_image(job_id: str, view: str):
    """SEE a real native UE MRQ frame of the five registered character models.

    Six fixed views: LINEUP, GPT, GEM, DS, CLA, ZERO. These images are
    SHA256 checked against a completed Windows UE job and forwarded over
    private SSH, with bounded size-only derivation if required. No fake
    concept art, no new rendering, no paths/URLs, no master approval.
    """
    result=get_ue_cast_review_png_rpc(job_id,view)
    if not result.get("ok"):
        return {"ok":False,"reason":result.get("reason","cast_review_unavailable")}
    try:
        data=choose_mcp_preview_png(result["data"])
    except (RuntimeError,ValueError,TypeError,OSError):
        return {"ok":False,"reason":"cast_review_transport_unavailable"}
    return Image(data=data,format="png")


@app.tool(annotations=READ)
def get_ue_signed_update_status() -> dict:
    """Read latest privileged signed-updater result and pending check request.

    No access to private signing key, bearer token, or arbitrary file paths.
    """
    return get_ue_signed_update_status_rpc()


@app.tool(annotations=WRITE)
def request_ue_signed_update() -> dict:
    """Ask the Windows updater to check for a pinned Ed25519-signed release.

    Creates one durable request for its NEXT 5-minute scheduled poll; never
    runs PowerShell, changes SSH or installs unverified code. Requires the
    separately bootstrapped privileged signed updater; the response is
    queued/not-ready, not proof that a version was installed. Check status
    and get_ue_worker_status to confirm actual installed Worker version.
    """
    return request_ue_signed_update_rpc()


@app.tool(annotations=READ)
def get_ue_hub_signed_update_status() -> dict:
    """Read sanitized root-owned VPS signed Hub update receipt only.

    Never disclose credentials, local paths or generic daemon status logs.
    """
    import json
    from pathlib import Path
    file = Path("/opt/comfyui-director-hub/ue_hub_signed_update_status.json")
    try:
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 1024:
            return {"ok": True, "status": "not_configured",
                    "hub_api_version": UE_HUB_API_VERSION}
        item = json.loads(file.read_text(encoding="ascii"))
        if type(item) is not dict:
            return {"ok": False, "reason": "invalid_update_receipt"}
        allowed = ("status", "version", "reason")
        return {"ok": True, "hub_api_version": UE_HUB_API_VERSION,
                **{k: item[k] for k in allowed if
                   k in item and type(item[k]) is str and len(item[k]) <= 100}}
    except (OSError, UnicodeError, ValueError, TypeError):
        return {"ok": False, "reason": "invalid_update_receipt"}


if __name__ == "__main__":
    app.run(transport="streamable-http")
