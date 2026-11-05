#!/usr/bin/env bash
# Director Hub V0.6: unify VPS status and staged power requests on port 8892.
# NEVER invokes GPU start/stop APIs; keeps Microsoft/Jipite approval isolated.
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
for name in director-hub-mcp director-hub-bridge director-power-mcp director-mobile-v06; do
    systemctl is-active --quiet "$name" || fail "Required service $name inactive"
done
[[ -x "$PYTHON" && -f "$DB" && ! -L "$DB" ]] || fail "Existing Python or approval DB missing"
[[ -d "$HUB" && ! -L "$HUB" && -d "$POWER" && ! -L "$POWER" ]] || fail "Existing installation missing"
for name in power_ops.py power_write_mcp.py vps_unified_status.py \
            hub_rpc.py hub_app.py director-hub-mcp.service; do
    [[ -f "$SRC/$name" && ! -L "$SRC/$name" ]] || fail "Missing source $name"
done
for item in "$POWER/power_ops.py" "$POWER/power_write_mcp.py" \
            "$HUB/hub_rpc.py" "$HUB/hub_app.py" "$UNIT"; do
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
cp -p "$HUB/hub_rpc.py" "$BACKUP/hub_rpc.py"
cp -p "$HUB/hub_app.py" "$BACKUP/hub_app.py"
cp -p "$UNIT" "$BACKUP/director-hub-mcp.service"
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
        cp -p "$BACKUP/hub_rpc.py" "$HUB/hub_rpc.py" || :
        cp -p "$BACKUP/hub_app.py" "$HUB/hub_app.py" || :
        cp -p "$BACKUP/director-hub-mcp.service" "$UNIT" || :
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
        echo "Rollback attempted; inspect services. Backup: $BACKUP" >&2
    fi
    exit "$code"
}
trap 'restore_on_exit $?' EXIT
install -o root -g root -m 0644 "$SRC/power_ops.py" "$POWER/power_ops.py"
install -o root -g root -m 0644 "$SRC/power_write_mcp.py" "$POWER/power_write_mcp.py"
install -o root -g root -m 0644 "$SRC/vps_unified_status.py" "$POWER/vps_unified_status.py"
install -o root -g root -m 0644 "$SRC/hub_rpc.py" "$HUB/hub_rpc.py"
install -o root -g root -m 0644 "$SRC/hub_app.py" "$HUB/hub_app.py"
install -o root -g root -m 0644 "$SRC/director-hub-mcp.service" "$UNIT"
"$PYTHON" -m py_compile "$POWER"/power_ops.py "$POWER"/power_write_mcp.py \
    "$POWER"/vps_unified_status.py "$HUB"/hub_rpc.py "$HUB"/hub_app.py
systemctl daemon-reload
systemctl restart director-power-mcp director-hub-mcp
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
      "request_gpu_start","request_gpu_stop","get_power_request_status"}
hub={"get_studio_status","get_queue_summary","list_h3_nodes","list_h3_workflows",
     "get_h3_workflow_structure","audit_h3_workflow","get_h3_node_inputs",
     "get_upgrade_readiness","get_control_center_status","get_gpu_power_status",
     "request_gpu_start","request_gpu_stop","get_power_request_status"}
for attempt in range(8):
    try:
        for port,expected in ((8892,core),(8896,hub)):
            actual={item["name"] for item in rpc(port,"tools/list",{})["tools"]}
            if actual!=expected: raise RuntimeError("Unexpected registry at "+str(port))
            stat=read(port,"get_gpu_power_status")
            if not stat.get("ok") or stat.get("state") not in (
                "Stopped","Running","Starting","Stopping"):
                raise RuntimeError("Read-only status backend unavailable")
            if not read(port,"get_control_center_status").get("configured"):
                raise RuntimeError("Provider configuration unavailable")
        print("PASS: VPS unified core 6 tools; Hub 13 tools; state via both; no power operation")
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
