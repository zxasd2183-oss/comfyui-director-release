#!/usr/bin/env bash
# Safe additive V0.9 production upgrade: backups, tests, no Nginx or GPU.
set -Eeuo pipefail
umask 077
fail() { echo "ERROR: $*" >&2; exit 2; }
[[ "$EUID" -eq 0 ]] || fail "Run with sudo on VPS"
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/director-studio
UNIT=/etc/systemd/system/director-studio.service
DB=/var/lib/director-studio/studio.sqlite
FILES="studio_server.py studio_identity.py session_store.py studio_brain.py studio_backend.py studio_core.py production_core.py production_web.py production_manage.py visual_library.py character_library.py character_library_v2.py shot_character_bindings.py scene_library.py manage.py index.html login.html login.css studio.css studio.js"
systemctl is-active --quiet director-studio || fail "Existing Studio not active"
systemctl is-active --quiet director-hub-mcp || fail "Director Hub not active"
[[ -d "$DEST" && ! -L "$DEST" && -f "$UNIT" ]] || fail "Existing Studio missing"
for f in $FILES; do
  [[ -f "$SRC/$f" && ! -L "$SRC/$f" ]] || fail "Missing trusted source $f"
done
python3 -m compileall -q "$SRC"
python3 -m unittest discover -s "$SRC/tests" -p 'test_*.py' -q
BACKUP="$(mktemp -d /var/tmp/director-studio-v09-backup-XXXXXXXX)"
chmod 0700 "$BACKUP"
mkdir -m 0700 "$BACKUP/files"
for f in $FILES; do
  if [[ -f "$DEST/$f" && ! -L "$DEST/$f" ]]; then
    cp -p "$DEST/$f" "$BACKUP/files/$f"
  elif [[ -e "$DEST/$f" || -L "$DEST/$f" ]]; then
    fail "Unsafe installed file: $f"
  fi
done
cp -p "$UNIT" "$BACKUP/director-studio.service"
if [[ -f "$DB" && ! -L "$DB" ]]; then
  python3 - "$DB" "$BACKUP/studio.sqlite" <<'PY'
import sqlite3,sys
from pathlib import Path
source=sqlite3.connect("file:"+Path(sys.argv[1]).as_posix()+"?mode=ro",uri=True)
target=sqlite3.connect(sys.argv[2])
try:
    source.backup(target)
finally:
    target.close()
    source.close()
Path(sys.argv[2]).chmod(0o600)
PY
fi
COMMITTED=0
restore() {
  local rc="$1"
  trap - EXIT
  if (( ! COMMITTED )); then
    echo "V0.9 upgrade failed; restoring previous Studio code/service." >&2
    for f in $FILES; do
      if [[ -f "$BACKUP/files/$f" ]]; then
        cp -p "$BACKUP/files/$f" "$DEST/$f" || :
      else
        rm -f "$DEST/$f" || :
      fi
    done
    cp -p "$BACKUP/director-studio.service" "$UNIT" || :
    systemctl daemon-reload || :
    systemctl restart director-studio || :
    echo "Check recovery; private backup: $BACKUP" >&2
  fi
  exit "$rc"
}
trap 'restore $?' EXIT
bash "$SRC/install-v08.sh"
python3 - <<'PY'
import json,urllib.request
with urllib.request.urlopen("http://127.0.0.1:8900/api/v1/snapshot",timeout=6) as response:
    value=json.load(response)
assert value["mode"]=="operator_ledger_only"
assert value["production"]["version"]=="0.9.0"
assert value["production"]["audit_chain_verified"] is True
assert value["production"]["controls"]["gpu_power"] is False
print("PASS: Existing studio ledger retained; V0.9 production foundation live")
PY
systemctl is-active --quiet director-hub-mcp || fail "Hub unexpectedly inactive"
COMMITTED=1
echo "SUCCESS: Director Studio V0.9 production foundation installed"
echo "Previous version and consistent legacy DB backup: $BACKUP"
echo "Production DB: /var/lib/director-studio/production.sqlite"
echo "Nginx/HTTPS auth, GPU, phone approval and OIDC unchanged"
