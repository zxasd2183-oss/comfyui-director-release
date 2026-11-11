#!/usr/bin/env bash
# Add the UE Worker tools to existing Director Hub. No nginx or SSH changes.
# Run from a checkout of this feature branch on the Ubuntu VPS.
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo" >&2
  exit 1
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST=/opt/comfyui-director-hub
SERVICE=director-hub-mcp.service
TOKEN=/etc/director-ue-worker.token
DROPIN=/etc/systemd/system/director-hub-mcp.service.d/ue-worker.conf
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP="/root/director-ue-hub-backup-${STAMP}"

[[ -f "$HERE/hub_app.py" && -f "$HERE/ue_worker_rpc.py" ]] || {
  echo "Missing source files" >&2; exit 1;
}
[[ -f "$DEST/hub_app.py" && -f /etc/systemd/system/director-hub-mcp.service ]] || {
  echo "Expected deployed Hub not found; no changes" >&2; exit 1;
}
id directorpower >/dev/null
systemctl is-active --quiet "$SERVICE" || {
  echo "Existing Hub not active; refusing to deploy" >&2; exit 1;
}
[[ -f "$TOKEN" && ! -L "$TOKEN" ]] || {
  echo "Provision the worker token at $TOKEN first" >&2; exit 1;
}
chown root:directorpower "$TOKEN"
chmod 0640 "$TOKEN"
python3 - "$TOKEN" <<'PY'
import pathlib, re, sys
value = pathlib.Path(sys.argv[1]).read_text(encoding="ascii").strip()
if not re.fullmatch(r"[0-9a-f]{64}", value):
    raise SystemExit("Invalid token format")
PY

# Ensure the local SSH reverse tunnel reaches a live Windows HTTP worker.
# An unauthorized HTTP request must get 401 (not 200 or a timeout).
status="$(curl --noproxy '*' -sS -m 5 -o /dev/null -w '%{http_code}' \
    http://127.0.0.1:18910/v1/status || true)"
[[ "$status" == "401" ]] || {
  echo "UE tunnel/agent missing (unauthenticated status HTTP $status)" >&2
  exit 1
}

python3 -m py_compile "$HERE/hub_app.py" "$HERE/ue_worker_rpc.py"
mkdir -p "$BACKUP"
chmod 0700 "$BACKUP"
cp -p "$DEST/hub_app.py" "$BACKUP/hub_app.py"
if [[ -f "$DEST/ue_worker_rpc.py" ]]; then
  cp -p "$DEST/ue_worker_rpc.py" "$BACKUP/ue_worker_rpc.py"
fi
if [[ -e "$DROPIN" ]]; then
  cp -p "$DROPIN" "$BACKUP/ue-worker.conf"
fi
mkdir -p "$(dirname "$DROPIN")"

restore() {
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    echo "Deployment failed; restoring Hub from $BACKUP" >&2
    cp -p "$BACKUP/hub_app.py" "$DEST/hub_app.py"
    if [[ -f "$BACKUP/ue_worker_rpc.py" ]]; then
      cp -p "$BACKUP/ue_worker_rpc.py" "$DEST/ue_worker_rpc.py"
    else
      rm -f "$DEST/ue_worker_rpc.py"
    fi
    if [[ -f "$BACKUP/ue-worker.conf" ]]; then
      cp -p "$BACKUP/ue-worker.conf" "$DROPIN"
    else
      rm -f "$DROPIN"
    fi
    systemctl daemon-reload
    systemctl restart "$SERVICE" || true
  fi
  exit "$rc"
}
trap restore EXIT

install -o directorpower -g directorpower -m 0644 "$HERE/hub_app.py" "$DEST/hub_app.py"
install -o directorpower -g directorpower -m 0644 "$HERE/ue_worker_rpc.py" "$DEST/ue_worker_rpc.py"
cat >"$DROPIN" <<'CONF'
[Service]
Environment=DIRECTOR_UE_WORKER_ENABLED=1
Environment=DIRECTOR_UE_WORKER_TOKEN_FILE=/etc/director-ue-worker.token
CONF
chmod 0644 "$DROPIN"
systemctl daemon-reload
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE"

# Exercise the same adapter that Hub invokes, as its service account.
runuser -u directorpower -- env DIRECTOR_UE_WORKER_ENABLED=1 \
    DIRECTOR_UE_WORKER_TOKEN_FILE="$TOKEN" \
    PYTHONPATH="$DEST" python3 - <<'PY'
from ue_worker_rpc import call_ue_worker
result = call_ue_worker("get_ue_worker_status")
if not result.get("ok") or result.get("node_id") != "ue-worker-01":
    raise SystemExit("UE Worker authenticated status failed: " + str(result.get("reason")))
print("Windows UE Worker authenticated tunnel: OK")
PY
trap - EXIT
echo "Director Hub UE extension installed, backup: $BACKUP"
echo "No other services, nginx, SSH or GPU controls were changed."
