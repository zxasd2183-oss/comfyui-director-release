#!/usr/bin/env bash
# One-time narrowly scoped fix for an older Hub's owner-direct power tool allowlist.
# No GPU power action, no credentials, no phone or browser approval.
set -Eeuo pipefail
umask 077
die(){ printf 'BLOCKED: %s\n' "$*" >&2; exit 2; }
(( EUID == 0 )) || die "root_required"
(( $# == 0 )) || die "no_arguments_allowed"
SRC="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SRC/.." && pwd)"
HUB=/opt/comfyui-director-hub
TARGET="$HUB/hub_rpc.py"
SOURCE="$SRC/hub_rpc.py"
PY=/opt/comfyui-director-control/.venv/bin/python
SERVICE=director-hub-mcp.service
# Reviewed blobs: old character-library Hub (direct route absent) and the
# existing audited owner-direct version (direct route included).
OLD_BLOB=f068c62bc49ac248a2eba2031453edd79ec2dd8b
NEW_BLOB=29e8274a93b7c316fd91570c4d4ccf405c45a4d5

[[ -x "$PY" && -d "$HUB" && ! -L "$HUB" ]] || die "hub_runtime_missing_or_unsafe"
[[ -f "$TARGET" && ! -L "$TARGET" ]] || die "installed_hub_router_missing_or_unsafe"
[[ -f "$SOURCE" && ! -L "$SOURCE" ]] || die "reviewed_router_missing_or_unsafe"
[[ "$(git -C "$REPO" branch --show-current)" == main ]] || die "reviewed_main_only"
git -C "$REPO" diff --quiet -- vps-control/hub_rpc.py || die "local_router_modified"
[[ "$(git -C "$REPO" hash-object "$SOURCE")" == "$NEW_BLOB" ]] ||
  die "reviewed_router_blob_mismatch"
[[ "$(stat -c %u "$TARGET")" == 0 ]] || die "installed_router_not_root_owned"
systemctl is-active --quiet "$SERVICE" || die "hub_service_not_active"
systemctl is-active --quiet director-power-mcp.service || die "power_service_not_active"

INSTALLED_BLOB="$(git -C "$REPO" hash-object "$TARGET")"
if [[ "$INSTALLED_BLOB" == "$NEW_BLOB" ]]; then
  echo "SUCCESS: Hub owner-direct router already current; no service change"
  exit 0
fi
[[ "$INSTALLED_BLOB" == "$OLD_BLOB" ]] ||
  die "installed_router_not_known_audited_pre_direct_version"

"$PY" -m py_compile "$SOURCE"
BACKUP="$(mktemp -d /var/lib/comfyui-director-power/hub-route-backup.XXXXXXXX)"
chmod 0700 "$BACKUP"
cp -p -- "$TARGET" "$BACKUP/hub_rpc.py"
COMMITTED=0
rollback(){
  if (( ! COMMITTED )); then
    echo "Restoring previously installed Hub router after failed verification." >&2
    STAGED_RESTORE="$(mktemp "$HUB/.hub-router-rollback.XXXXXXXX")"
    install -o root -g root -m 0644 "$BACKUP/hub_rpc.py" "$STAGED_RESTORE"
    mv -f -- "$STAGED_RESTORE" "$TARGET"
    systemctl restart "$SERVICE" || :
  fi
}
trap rollback EXIT

STAGED="$(mktemp "$HUB/.hub-router-update.XXXXXXXX")"
install -o root -g root -m 0644 "$SOURCE" "$STAGED"
mv -f -- "$STAGED" "$TARGET"
[[ "$(git -C "$REPO" hash-object "$TARGET")" == "$NEW_BLOB" ]] ||
  die "installed_router_verification_failed"
systemctl restart "$SERVICE"
systemctl is-active --quiet "$SERVICE" || die "hub_service_restart_failed"

# NO start_gpu_now or stop_gpu_now calls: check only local routing and
# owner-direct read-only status; never require the GPU to be running.
PYTHONPATH="$HUB" "$PY" - <<'PY'
import time
import hub_rpc
assert hub_rpc.check_args("start_gpu_now",{}) == {}
assert hub_rpc.check_args("stop_gpu_now",{}) == {}
for tool in ("start_gpu_now", "stop_gpu_now"):
    assert hub_rpc.endpoint(tool) == "http://127.0.0.1:8892/mcp"
for attempt in range(8):
    status=hub_rpc.call("get_control_center_status")
    if (status.get("configured") is True and
        status.get("instance_selected") is True and
        status.get("gpu_control_enabled") is True and
        status.get("mode") == "owner_direct"):
        print("SUCCESS: Hub router forwards immediate power tools to private VPS core")
        print("No GPU power operation executed; no phone/browser approval required")
        break
    if attempt==7:
        raise SystemExit("BLOCKED: live_owner_direct_status_not_verified")
    time.sleep(2)
PY
COMMITTED=1
echo "SUCCESS: private Hub power routing restored; earlier router backed up."
