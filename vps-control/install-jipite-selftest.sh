#!/usr/bin/env bash
# Upgrade only the installed, Microsoft-gated Jipite Android approval API.
# Adds NON-POWER biometric key selftest. No GPU permission, TOTP, Nginx,
# existing device binding, pairing secret, database or push credentials change.
set -euo pipefail
umask 077

[[ "$EUID" -eq 0 ]] || { echo "Please run via sudo on your own VPS" >&2; exit 2; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP=/opt/comfyui-director-power
PY=/opt/comfyui-director-control/.venv/bin/python
SERVICE=director-mobile-v06
BACKUPS=/var/backups
FILES=(mobile_v06_api.py mobile_v06_selftest.py)

echo "[1/4] Validating existing approval server and source..."
for c in systemctl curl install cp cmp mktemp; do command -v "$c" >/dev/null; done
[[ -x "$PY" && -d "$APP" && ! -L "$APP" ]] || {
  echo "ABORT: trusted VPS API Python/runtime missing; no changes made" >&2; exit 3;
}
for unit in "$SERVICE" director-power-approval jipite-immediate-notify.service; do
  systemctl is-active --quiet "$unit" || {
    echo "ABORT: prerequisite $unit is not active" >&2; exit 3;
  }
done
for item in mobile_v06_api.py mobile_v06_selftest.py; do
  [[ -f "$HERE/$item" && ! -L "$HERE/$item" ]] || {
    echo "ABORT: source $item is missing/unsafe" >&2; exit 3;
  }
done
for item in mobile_v06_core.py mobile_v06_api.py; do
  [[ -f "$APP/$item" && ! -L "$APP/$item" ]] || {
    echo "ABORT: existing approval service source $item missing or symlinked" >&2; exit 3;
  }
done
[[ ! -L "$APP/mobile_v06_selftest.py" ]] || {
  echo "ABORT: selftest destination is a symlink" >&2; exit 3;
}
[[ -d "$BACKUPS" && ! -L "$BACKUPS" ]] || {
  echo "ABORT: no safe root-only backup folder" >&2; exit 3;
}

echo "[2/4] Backing up original API files and installing verified source..."
backup="$(mktemp -d "$BACKUPS/jipite-selftest.XXXXXXXX")"
chmod 0700 "$backup"
cp -p "$APP/mobile_v06_api.py" "$backup/mobile_v06_api.py"
had_selftest=0
if [[ -f "$APP/mobile_v06_selftest.py" ]]; then
  cp -p "$APP/mobile_v06_selftest.py" "$backup/mobile_v06_selftest.py"
  had_selftest=1
fi
installed=0
completed=0
rollback() {
  rc=$?
  if [[ "$completed" -eq 0 && "$installed" -eq 1 ]]; then
    echo "Selftest deploy failed (rc=$rc); restoring original approval API..." >&2
    cp -p "$backup/mobile_v06_api.py" "$APP/mobile_v06_api.py"
    if [[ "$had_selftest" -eq 1 ]]; then
      cp -p "$backup/mobile_v06_selftest.py" "$APP/mobile_v06_selftest.py"
    else
      rm -f "$APP/mobile_v06_selftest.py"
    fi
    systemctl restart "$SERVICE" || true
    systemctl is-active --quiet "$SERVICE" || \
      echo "WARNING: old approval service not healthy after rollback; investigate manually" >&2
    echo "Backup retained: $backup" >&2
  fi
}
trap rollback EXIT
installed=1
for item in "${FILES[@]}"; do
  install -o root -g root -m 0644 "$HERE/$item" "$APP/$item"
done
# Verify syntax and required imports using the EXISTING virtual environment.
"$PY" -m py_compile "$APP/mobile_v06_selftest.py" "$APP/mobile_v06_api.py"
(cd "$APP" && "$PY" -c 'import mobile_v06_core, mobile_v06_selftest, mobile_v06_api; print("Safe Python module imports: OK")')

echo "[3/4] Restarting ONLY the mobile API; checking pre-existing protections..."
systemctl restart "$SERVICE"
health=0
for i in $(seq 1 16); do
  code="$(curl -sS --max-time 3 --output /dev/null \
    --write-out '%{http_code}' http://127.0.0.1:8895/health 2>/dev/null)" || code=""
  if [[ "$code" == 200 ]]; then health=1; break; fi
  sleep 0.5
done
[[ "$health" == 1 ]] || {
  echo "ABORT: local mobile health unavailable" >&2; exit 4;
}
probe() {
  curl -sS --max-time 8 -X POST \
    -H 'Content-Type: application/json' --data '{}' \
    -o /dev/null -w '%{http_code}' "$1"
}
selftest_anon="$(probe https://jipite.borealos.cn/api/v1/mobile/selftest_challenge)" || selftest_anon=unreachable
verify_anon="$(probe https://jipite.borealos.cn/api/v1/mobile/selftest_verify)" || verify_anon=unreachable
original_anon="$(probe https://jipite.borealos.cn/api/v1/mobile/pending)" || original_anon=unreachable
echo "Selftest challenge without Microsoft token: HTTP $selftest_anon (401 expected)"
echo "Selftest verification without Microsoft token: HTTP $verify_anon (401 expected)"
echo "Original pending API without Microsoft token: HTTP $original_anon (401 expected)"
if [[ "$selftest_anon" != 401 || "$verify_anon" != 401 || "$original_anon" != 401 ]]; then
  echo "ABORT: public API auth gate failed validation" >&2; exit 5;
fi
systemctl is-active --quiet "$SERVICE"
systemctl is-active --quiet director-power-approval

echo "[4/4] Selftest API ready; no GPU power operation was performed."
completed=1
trap - EXIT
echo "Deployed Jipite biometric selftest; backup: $backup"
echo "Existing Microsoft identity, TOTP, GPU controller, static APK mirror and hourly fallback: unchanged"
