#!/usr/bin/env bash
# Conditional one-time repair of existing local power service.
# Never sends Start/Stop requests; no phone/website approval per later operation.
set -Eeuo pipefail
umask 077
fail(){ printf 'BLOCKED: %s\n' "$*" >&2; exit 2; }
(( EUID == 0 )) || fail "root_required"
(( $# == 0 )) || fail "no_arguments_supported"
SRC="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SRC/.." && pwd)"
POWER=/opt/comfyui-director-power
PY=/opt/comfyui-director-control/.venv/bin/python
DB=/var/lib/comfyui-director-power/requests.db
SERVICE=director-power-mcp.service
HUB_SERVICE=director-hub-mcp.service
[[ -x "$PY" && -d "$POWER" && ! -L "$POWER" ]] || fail "known_power_service_install_required"
[[ -f "$DB" && ! -L "$DB" ]] || fail "existing_power_database_required"
[[ "$(git -C "$REPO" branch --show-current)" == "main" ]] || fail "reviewed_main_only"
# FILE OPERATIONS BEGIN: isolated function definitions are exercised in CI.
# Only power_direct.py is a legitimate newly introduced module. Missing core
# files remain an installation-integrity failure.
POWER_FILES=(power_ops.py power_direct.py power_write_mcp.py vps_unified_status.py)
ORIGINALLY_MISSING=()
check_target_files(){
  local name
  for name in "${POWER_FILES[@]}"; do
    if [[ -e "$POWER/$name" || -L "$POWER/$name" ]]; then
      [[ -f "$POWER/$name" && ! -L "$POWER/$name" ]] ||
        fail "existing_power_file_missing_or_unsafe"
    else
      [[ "$name" == power_direct.py ]] ||
        fail "required_existing_power_file_missing"
      ORIGINALLY_MISSING+=("$name")
    fi
  done
}
backup_target_files(){
  local name
  for name in "${POWER_FILES[@]}"; do
    if [[ -f "$POWER/$name" && ! -L "$POWER/$name" ]]; then
      cp -p "$POWER/$name" "$BACKUP/$name"
    elif [[ "$name" == power_direct.py &&
            " ${ORIGINALLY_MISSING[*]} " == *" power_direct.py "* &&
            ! -e "$POWER/$name" && ! -L "$POWER/$name" ]]; then
      : # Only the file that was absent at preflight may have no backup.
    else
      fail "existing_power_file_changed_before_backup"
    fi
  done
}
restore_target_files(){
  local name
  for name in "${POWER_FILES[@]}"; do
    if [[ -f "$BACKUP/$name" && ! -L "$BACKUP/$name" ]]; then
      # Never follow a symlink inserted into the installed location.
      [[ ! -L "$POWER/$name" ]] || fail "unsafe_power_rollback_target"
      cp -p "$BACKUP/$name" "$POWER/$name" ||
        fail "existing_power_file_restore_failed"
    elif [[ "$name" == power_direct.py && ! -e "$BACKUP/$name" && ! -L "$BACKUP/$name" ]]; then
      # First install: remove the newly created module; do not copy a
      # nonexistent backup. rm -f unlinks a dangling symlink, too.
      [[ ! -d "$POWER/$name" ]] || fail "unsafe_new_power_file_directory"
      rm -f -- "$POWER/$name" || fail "new_power_file_cleanup_failed"
    else
      fail "required_power_rollback_backup_missing"
    fi
  done
}
# FILE OPERATIONS END
check_target_files
for name in "${POWER_FILES[@]}"; do
  [[ -f "$SRC/$name" && ! -L "$SRC/$name" ]] || fail "reviewed_power_source_missing_or_unsafe"
  git -C "$REPO" diff --quiet -- "vps-control/$name" ||
    fail "reviewed_power_source_modified"
done
[[ -f "$SRC/diagnose_gpu_direct_power.py" && ! -L "$SRC/diagnose_gpu_direct_power.py" ]] ||
  fail "redacted_diagnostic_missing"
git -C "$REPO" diff --quiet -- vps-control/diagnose_gpu_direct_power.py ||
  fail "reviewed_diagnostic_modified"
systemctl is-active --quiet "$SERVICE" || fail "power_core_service_not_active"
systemctl is-active --quiet "$HUB_SERVICE" || fail "hub_service_not_active"

echo "Checking official cloud Describe endpoint (read-only; no GPU power action)..."
"$PY" "$SRC/diagnose_gpu_direct_power.py" || fail "provider_not_verified_no_change"

# Never steal an active GPU operation lock. Historical requests are untouched.
"$PY" - "$DB" "$POWER" <<'PY'
import sys,time
sys.path.insert(0,sys.argv[2])
from power_v03 import connect
with connect(sys.argv[1]) as db:
    n=db.execute("SELECT COUNT(*) FROM requests WHERE state='executing' OR "
                 "(state='pending' AND expires>?)",(time.time(),)).fetchone()[0]
if n:
    raise SystemExit("BLOCKED: outstanding GPU power request")
print("PASS: no active power requests")
PY

"$PY" -m py_compile "$SRC/power_ops.py" "$SRC/power_direct.py" "$SRC/power_write_mcp.py" "$SRC/vps_unified_status.py"
BACKUP="$(mktemp -d /var/lib/comfyui-director-power/owner-direct-backup.XXXXXXXX)"
chmod 0700 "$BACKUP"
backup_target_files
COMMITTED=0
cleanup(){
  if (( ! COMMITTED )); then
    echo "Restoring prior power service code after failed verification." >&2
    restore_target_files
    systemctl restart "$SERVICE" || :
  fi
}
trap cleanup EXIT

for name in "${POWER_FILES[@]}"; do
  # Refuse to overwrite a path created after initial validation. In
  # particular, do not follow a newly inserted symlink.
  if [[ "$name" == power_direct.py && " ${ORIGINALLY_MISSING[*]} " == *" power_direct.py "* ]]; then
    [[ ! -e "$POWER/$name" && ! -L "$POWER/$name" ]] ||
      fail "new_power_file_appeared_during_install"
  else
    [[ -f "$POWER/$name" && ! -L "$POWER/$name" ]] ||
      fail "existing_power_file_changed_during_install"
  fi
  install -o root -g root -m 0644 "$SRC/$name" "$POWER/$name"
done
systemctl restart "$SERVICE"
systemctl is-active --quiet "$SERVICE" || fail "power_service_restart_failed"

# Verify actual provider/instance via ONLY local read-only MCP calls.
# Never invoke the registered start_gpu_now or stop_gpu_now tools here.
"$PY" - <<'PY'
import json,time
from urllib.request import Request,ProxyHandler,build_opener
opener=build_opener(ProxyHandler({}))
def rpc(port,name):
    body={"jsonrpc":"2.0","id":1,"method":"tools/call",
          "params":{"name":name,"arguments":{}}}
    req=Request("http://127.0.0.1:%d/mcp"%port,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type":"application/json",
                 "Accept":"application/json, text/event-stream",
                 "Mcp-Protocol-Version":"2025-03-26",
                 "Host":"127.0.0.1:%d"%port})
    with opener.open(req,timeout=15) as response:raw=response.read(65537)
    if len(raw)>65536:raise RuntimeError("oversized_mcp_reply")
    out=json.loads(raw)
    data=out.get("result",{})
    if out.get("error") or data.get("isError"):
        raise RuntimeError("mcp_read_failed")
    if isinstance(data.get("structuredContent"),dict):
        return data["structuredContent"]
    texts=[x.get("text") for x in data.get("content",[])
           if isinstance(x,dict) and x.get("type")=="text"]
    if len(texts)!=1:raise RuntimeError("unexpected_mcp_result")
    return json.loads(texts[0])
for attempt in range(8):
    try:
        for port in (8892,8898):
            status=rpc(port,"get_control_center_status")
            state=rpc(port,"get_gpu_power_status")
            if not (status.get("configured") is True and
                    status.get("instance_selected") is True and
                    status.get("gpu_control_enabled") is True and
                    status.get("mode")=="owner_direct"):
                raise RuntimeError("owner_direct_not_enabled")
            if (state.get("ok") is not True or
                    state.get("state") not in ("Stopped","Running","Starting","Stopping")):
                raise RuntimeError("provider_state_not_verified")
        print("SUCCESS: owner_direct validated through private VPS core and Hub")
        print("No GPU power operation performed; per-action phone/browser approval unnecessary.")
        break
    except Exception:
        if attempt==7:raise SystemExit("BLOCKED: owner_direct_runtime_verification_failed")
        time.sleep(2)
PY

COMMITTED=1
echo "SUCCESS: direct GPU power core restored and verified; existing files backed up."
echo "STOP remains fail-closed until ComfyUI queue verified empty and outputs saved."
echo "Backup held under root-only /var/lib/comfyui-director-power/."
