#!/usr/bin/env bash
# Director Hub: protected owner direct GPU actions plus legacy staged requests.
# Installer itself NEVER executes a provider GPU power operation.
set -Eeuo pipefail
umask 077
fail() { echo "ERROR: $*" >&2; exit 2; }
[[ "$EUID" -eq 0 ]] || fail "Run on VPS with sudo"
(( $# <= 1 )) || fail "Usage: install-hub-v06.sh [--retire-legacy-vps]"
RETIRE=0
if (( $# == 1 )); then
    [[ "$1" == "--retire-legacy-vps" ]] || fail "Unknown option"
    RETIRE=1
fi
SRC="$(cd "$(dirname "$0")" && pwd)"
PYTHON=/opt/comfyui-director-control/.venv/bin/python
POWER=/opt/comfyui-director-power
HUB=/opt/comfyui-director-hub
DB=/var/lib/comfyui-director-power/requests.db
UNIT=/etc/systemd/system/director-hub-mcp.service
# Existing Nginx must use the same private bridge that this upgrade deploys.
# Never silently disrupt the production MCP path to reuse Glacier's 8897.
HUB_SNIPPET=/etc/nginx/snippets/jipite-hub.conf
[[ -f "$HUB_SNIPPET" && ! -L "$HUB_SNIPPET" ]] ||
    fail "Hub Nginx snippet missing/unsafe; inspect before changing ports"
grep -Fq 'proxy_pass http://127.0.0.1:8899;' "$HUB_SNIPPET" ||
    fail "Live Hub Nginx upstream differs from reserved bridge port 8899"
grep -Fq 'proxy_set_header Host 127.0.0.1:8899;' "$HUB_SNIPPET" ||
    fail "Live Hub Nginx Host differs from bridge port 8899"
for name in director-hub-mcp director-hub-bridge director-power-mcp director-mobile-v06; do
    systemctl is-active --quiet "$name" || fail "Required service $name inactive"
done
[[ -x "$PYTHON" && -f "$DB" && ! -L "$DB" ]] || fail "Existing Python or approval DB missing"
[[ -d "$HUB" && ! -L "$HUB" && -d "$POWER" && ! -L "$POWER" ]] || fail "Existing installation missing"
for name in power_ops.py power_direct.py power_write_mcp.py vps_unified_status.py \
            hub_rpc.py hub_brain.py hub_file_sync.py hub_sync_jobs.py hub_app.py hub_bridge.py director-hub-mcp.service director-power-mcp.service; do
    [[ -f "$SRC/$name" && ! -L "$SRC/$name" ]] || fail "Missing source $name"
done
for item in "$POWER/power_ops.py" "$POWER/power_write_mcp.py" \
            "$HUB/hub_rpc.py" "$HUB/hub_app.py" "$HUB/hub_bridge.py" "$UNIT" \
            /etc/systemd/system/director-power-mcp.service; do
    [[ -f "$item" && ! -L "$item" ]] || fail "Installed file missing or symlink"
done
# Refuse upgrade while a biometric approval may be underway.
"$PYTHON" - "$DB" <<'PY'
import sqlite3,sys,time
db=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True,timeout=5)
active=db.execute("SELECT COUNT(*) FROM requests WHERE (state='pending' AND expires>?) OR state='executing'",(time.time(),)).fetchone()[0]
db.close()
if active: raise SystemExit("BLOCKED: pending/executing GPU operation, cannot restart services")
print("PASS: no pending or executing power operations")
PY
LEGACY_BRIDGE_ACTIVE=0
systemctl is-active --quiet director-vps-bridge.service && LEGACY_BRIDGE_ACTIVE=1
if (( RETIRE )); then
    if systemctl is-active --quiet director-vps-named-tunnel.service; then
        fail "Refuse to retire dependencies of a running legacy named tunnel"
    fi
    systemctl is-active --quiet director-vps-control.service \
        || fail "Legacy status service already offline"
fi

BACKUP="$(mktemp -d /var/tmp/director-hub-v06-backup-XXXXXXXX)"
chmod 0700 "$BACKUP"
cp -p "$POWER/power_ops.py" "$BACKUP/power_ops.py"
cp -p "$POWER/power_write_mcp.py" "$BACKUP/power_write_mcp.py"
HAD_DIRECT=0
if [[ -f "$POWER/power_direct.py" && ! -L "$POWER/power_direct.py" ]]; then
    HAD_DIRECT=1
    cp -p "$POWER/power_direct.py" "$BACKUP/power_direct.py"
fi
cp -p "$HUB/hub_rpc.py" "$BACKUP/hub_rpc.py"
cp -p "$HUB/hub_app.py" "$BACKUP/hub_app.py"
HAD_SYNC_JOBS=0
if [[ -f "$HUB/hub_sync_jobs.py" && ! -L "$HUB/hub_sync_jobs.py" ]]; then
    HAD_SYNC_JOBS=1
    cp -p "$HUB/hub_sync_jobs.py" "$BACKUP/hub_sync_jobs.py"
fi
HAD_FILE_SYNC=0
if [[ -f "$HUB/hub_file_sync.py" && ! -L "$HUB/hub_file_sync.py" ]]; then
    HAD_FILE_SYNC=1
    cp -p "$HUB/hub_file_sync.py" "$BACKUP/hub_file_sync.py"
fi
cp -p "$HUB/hub_bridge.py" "$BACKUP/hub_bridge.py"
HAD_BRAIN=0
if [[ -f "$HUB/hub_brain.py" && ! -L "$HUB/hub_brain.py" ]]; then
    HAD_BRAIN=1
    cp -p "$HUB/hub_brain.py" "$BACKUP/hub_brain.py"
fi
cp -p "$UNIT" "$BACKUP/director-hub-mcp.service"
cp -p /etc/systemd/system/director-power-mcp.service "$BACKUP/director-power-mcp.service"
HAD_STATUS=0
if [[ -f "$POWER/vps_unified_status.py" ]]; then
    HAD_STATUS=1
    cp -p "$POWER/vps_unified_status.py" "$BACKUP/vps_unified_status.py"
fi
COMMITTED=0
restore_on_exit() {
    local code="$1"
    trap - EXIT
    if (( ! COMMITTED )); then
        echo "Upgrade failed: restoring old binaries and service unit" >&2
        cp -p "$BACKUP/power_ops.py" "$POWER/power_ops.py" || :
        cp -p "$BACKUP/power_write_mcp.py" "$POWER/power_write_mcp.py" || :
        if (( HAD_DIRECT )); then
            cp -p "$BACKUP/power_direct.py" "$POWER/power_direct.py" || :
        else
            rm -f "$POWER/power_direct.py" || :
        fi
        cp -p "$BACKUP/hub_rpc.py" "$HUB/hub_rpc.py" || :
        cp -p "$BACKUP/hub_app.py" "$HUB/hub_app.py" || :
        if (( HAD_SYNC_JOBS )); then
            cp -p "$BACKUP/hub_sync_jobs.py" "$HUB/hub_sync_jobs.py" || :
        else
            rm -f "$HUB/hub_sync_jobs.py" || :
        fi
        if (( HAD_FILE_SYNC )); then
            cp -p "$BACKUP/hub_file_sync.py" "$HUB/hub_file_sync.py" || :
        else
            rm -f "$HUB/hub_file_sync.py" || :
        fi
        cp -p "$BACKUP/hub_bridge.py" "$HUB/hub_bridge.py" || :
        if (( HAD_BRAIN )); then
            cp -p "$BACKUP/hub_brain.py" "$HUB/hub_brain.py" || :
        else
            rm -f "$HUB/hub_brain.py" || :
        fi
        cp -p "$BACKUP/director-hub-mcp.service" "$UNIT" || :
        cp -p "$BACKUP/director-power-mcp.service" /etc/systemd/system/director-power-mcp.service || :
        if (( HAD_STATUS )); then
            cp -p "$BACKUP/vps_unified_status.py" "$POWER/vps_unified_status.py" || :
        else
            rm -f "$POWER/vps_unified_status.py" || :
        fi
        systemctl daemon-reload || :
        if (( RETIRE )); then
            systemctl enable --now director-vps-control.service || :
            if (( LEGACY_BRIDGE_ACTIVE )); then
                systemctl enable --now director-vps-bridge.service || :
            fi
        fi
        systemctl restart director-power-mcp director-hub-mcp || :
        systemctl restart director-hub-bridge || :
        echo "Rollback attempted; inspect services. Backup: $BACKUP" >&2
    fi
    exit "$code"
}
trap 'restore_on_exit $?' EXIT
install -o root -g root -m 0644 "$SRC/power_ops.py" "$POWER/power_ops.py"
install -o root -g root -m 0644 "$SRC/power_write_mcp.py" "$POWER/power_write_mcp.py"
install -o root -g root -m 0644 "$SRC/power_direct.py" "$POWER/power_direct.py"
install -o root -g root -m 0644 "$SRC/vps_unified_status.py" "$POWER/vps_unified_status.py"
install -o root -g root -m 0644 "$SRC/hub_rpc.py" "$HUB/hub_rpc.py"
install -o root -g root -m 0644 "$SRC/hub_brain.py" "$HUB/hub_brain.py"
install -o root -g root -m 0644 "$SRC/hub_file_sync.py" "$HUB/hub_file_sync.py"
install -o root -g root -m 0644 "$SRC/hub_sync_jobs.py" "$HUB/hub_sync_jobs.py"
install -o root -g root -m 0644 "$SRC/hub_app.py" "$HUB/hub_app.py"
install -o root -g root -m 0644 "$SRC/hub_bridge.py" "$HUB/hub_bridge.py"
install -o root -g root -m 0644 "$SRC/director-hub-mcp.service" "$UNIT"
install -o root -g root -m 0644 "$SRC/director-power-mcp.service" /etc/systemd/system/director-power-mcp.service
"$PYTHON" -m py_compile "$POWER"/power_ops.py "$POWER"/power_write_mcp.py \
    "$POWER"/vps_unified_status.py "$POWER"/power_direct.py "$HUB"/hub_rpc.py "$HUB"/hub_brain.py "$HUB"/hub_file_sync.py "$HUB"/hub_sync_jobs.py "$HUB"/hub_app.py "$HUB"/hub_bridge.py
systemctl daemon-reload
systemctl restart director-power-mcp director-hub-mcp
systemctl restart director-hub-bridge
for name in director-power-mcp director-hub-mcp director-hub-bridge director-mobile-v06; do
    systemctl is-active --quiet "$name" || fail "Service did not recover: $name"
done

# Read-only local integration probe; never calls request_gpu_start/stop.
"$PYTHON" - <<'PY'
import json,time
from urllib.request import Request,build_opener,ProxyHandler
opener=build_opener(ProxyHandler({}))
def rpc(port,method,params):
    req=Request("http://127.0.0.1:%d/mcp"%port,
        data=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode(),
        headers={"Content-Type":"application/json",
                 "Accept":"application/json, text/event-stream",
                 "Mcp-Protocol-Version":"2025-03-26",
                 "Host":"127.0.0.1:%d"%port})
    with opener.open(req,timeout=12) as response: data=json.load(response)
    if "error" in data: raise RuntimeError("MCP transport error")
    return data["result"]
def read(port,name):
    result=rpc(port,"tools/call",{"name":name,"arguments":{}})
    if result.get("isError"): raise RuntimeError("MCP tool failed")
    data=result.get("structuredContent")
    if not isinstance(data,dict):
        values=[x.get("text","") for x in result.get("content",[])
                if isinstance(x,dict) and x.get("type")=="text"]
        data=json.loads(values[0]) if values else {}
    return data
core={"get_power_service_health","get_control_center_status","get_gpu_power_status",
      "request_gpu_start","request_gpu_stop","get_power_request_status",
      "start_gpu_now","stop_gpu_now"}
hub={
     "get_studio_status","get_queue_summary","list_h3_nodes","list_h3_workflows",
     "get_h3_workflow_structure","audit_h3_workflow","get_h3_node_inputs","get_upgrade_readiness",
     "get_control_center_status","get_gpu_power_status","start_gpu_now","stop_gpu_now",
     "request_gpu_start","request_gpu_stop","get_power_request_status","get_production_dashboard",
     "get_production_episode","get_production_scenes","get_production_episode_readiness","create_production_scene",
     "create_production_project","create_production_episode","add_production_shot","save_production_outline",
     "get_project_characters","create_project_character","update_project_character","link_project_character_visual",
     "sync_chatgpt_visual_to_studio","enqueue_chatgpt_visual_to_studio","get_chatgpt_visual_sync_status","list_recent_chatgpt_visual_syncs",
     "get_ue_worker_status","get_ue_worker_power_readiness","get_ue_worker_capabilities","get_ue_episode_assembly_readiness","prepare_ue_workspace","prepare_ue_hero_metahuman_project",
     "enqueue_ue_episode_timeline","enqueue_ue_stage_cameras","enqueue_ue_previs_stills","enqueue_ue_asset_audit","enqueue_ue_scene_candidates","enqueue_ue_cast_blueprints","enqueue_ue_cast_review","enqueue_ue_hero_metahuman_seed","enqueue_ue_hero_runtime_audit","enqueue_ue_hero_amber_eyes","get_ue_episode_job_status",
     "get_ue_job_logs","cancel_ue_job","get_ue_preview_image","get_ue_preview_thumbnail","get_ue_cast_review_image",
     "get_ue_signed_update_status","request_ue_signed_update","get_ue_hub_signed_update_status"
}
for attempt in range(8):
    try:
        for port,expected in ((8892,core),(8898,hub)):
            actual={item["name"] for item in rpc(port,"tools/list",{})["tools"]}
            if actual!=expected: raise RuntimeError("Unexpected registry at "+str(port))
            controller=read(port,"get_control_center_status")
            if not controller.get("configured") or not controller.get("instance_selected"):
                raise RuntimeError("Provider configuration unavailable")
            stat=read(port,"get_gpu_power_status")
            if stat.get("ok") is True:
                if stat.get("state") not in ("Stopped","Running","Starting","Stopping"):
                    raise RuntimeError("Unexpected GPU provider state")
            elif (
                # Retired/disabled cloud GPU may have a stale provider token.
                # This explicitly readonly state is NOT a power authorization.
                controller.get("gpu_control_enabled") is False and
                controller.get("mode") == "read_only" and
                stat.get("ok") is False and
                stat.get("mode") == "read_only" and
                stat.get("reason") == "provider_request_failed"
            ):
                print("PASS: GPU provider unavailable, cloud power disabled (read-only)")
            else:
                # Any enabled power controller must prove the real provider state.
                raise RuntimeError("Read-only status backend unavailable")
        print("PASS: VPS core 8 tools; Hub 57 tools; no GPU power operation")
        break
    except Exception:
        if attempt==7: raise
        time.sleep(2)
PY
if (( RETIRE )); then
    systemctl disable --now director-vps-bridge.service director-vps-control.service
    for name in director-power-mcp director-hub-mcp director-mobile-v06; do
        systemctl is-active --quiet "$name" || fail "Retirement destabilized service: $name"
    done
    echo "Retired redundant VPS status service and old bridge (8890/8891)"
else
    echo "Legacy 8890/8891 remain online until deliberate retirement"
fi
COMMITTED=1
echo "SUCCESS: Director Hub V0.6 deployed; ChatGPT URL/token unchanged"
echo "Mobile biometric approval and power DB unchanged; GPU never started/stopped"
echo "Private rollback backup: $BACKUP"
