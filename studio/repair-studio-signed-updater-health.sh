#!/usr/bin/env bash
# Exact one-time recovery for the already-bootstrapped Studio signed updater.
# No arbitrary command forwarding, no API secret mutation, no Studio app restart.
set -Eeuo pipefail
umask 077
die() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
(( EUID == 0 )) || die "Root required"
(( $# == 0 )) || die "No arguments accepted"
SRC="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SRC/.." && pwd)"
TARGET=/opt/director-studio-signed-updater/studio_signed_updater.py
STATE=/var/lib/director-studio-signed-updater
TIMER=director-studio-signed-update.timer
SERVICE=director-studio-signed-update.service
PY=/opt/comfyui-director-control/.venv/bin/python
OLD_COMMIT=885cdc39df79469b51b718e4a06dd2ffc1df37ad
FIX_COMMIT=615b3aeebfe16ff152e9ecf133ea8426842f1527

[[ -x "$PY" && -d "$STATE" && ! -L "$STATE" ]] || die "Updater runtime/state not bootstrapped"
[[ -f "$TARGET" && ! -L "$TARGET" && -f "$STATE/installed-version.txt" ]] || die "Existing updater missing or unsafe"
[[ -f "$SRC/studio_signed_updater.py" && ! -L "$SRC/studio_signed_updater.py" ]] || die "Reviewed source unavailable"
[[ "$(stat -c %u "$TARGET")" == 0 && "$(stat -c %a "$TARGET")" == 600 ]] || die "Installed updater owner/mode differs"
[[ "$(git -C "$ROOT" branch --show-current)" == main ]] || die "VPS repository must be checked out at trusted main"
git -C "$ROOT" merge-base --is-ancestor "$FIX_COMMIT" HEAD || die "VPS checkout missing the reviewed health fix"
git -C "$ROOT" diff --quiet -- studio/studio_signed_updater.py || die "Reviewed local updater source modified"
"$PY" -m py_compile "$SRC/studio_signed_updater.py"
grep -Fq 'info.get("mode") != "read_only_production_summary"' "$SRC/studio_signed_updater.py" || die "Reviewed health contract missing"
if grep -Fq 'info.get("ok") is not True' "$SRC/studio_signed_updater.py"; then
  die "Reviewed source still requires nonexistent ok field"
fi

if cmp -s "$SRC/studio_signed_updater.py" "$TARGET"; then
  echo "SUCCESS: Installed Studio updater already has reviewed health fix"
  exit 0
fi

# The only authorized input is the byte-for-byte first bootstrapped version.
EXPECTED="$(mktemp "$STATE/expected-old-updater.XXXXXXXX")"
trap 'rm -f "$EXPECTED"' EXIT
git -C "$ROOT" show "$OLD_COMMIT:studio/studio_signed_updater.py" > "$EXPECTED" ||
  die "Cannot verify initial trusted updater revision"
chmod 0600 "$EXPECTED"
cmp -s "$EXPECTED" "$TARGET" || die "Installed updater differs from known initial release; refuse replacement"

systemctl is-active --quiet director-studio.service || die "Studio service not healthy"
systemctl is-enabled --quiet "$TIMER" || die "Studio signed timer not enabled"
systemctl stop "$TIMER"
trap 'rm -f "$EXPECTED"; systemctl start "$TIMER" >/dev/null 2>&1 || :' EXIT
if systemctl is-active --quiet "$SERVICE"; then
  die "Signed update task is still active; refuse concurrent repair"
fi

BACKUP="$(mktemp "$STATE/pre-health-hotfix-backup.XXXXXXXX")"
cp -p "$TARGET" "$BACKUP"
chmod 0600 "$BACKUP"
TEMP="$(mktemp "$STATE/new-updater.XXXXXXXX")"
install -o root -g root -m 0600 "$SRC/studio_signed_updater.py" "$TEMP"
# Atomic replacement requires the source and target on the same filesystem:
# stage a second hidden file in the installed updater directory.
STAGED="$(mktemp "$(dirname "$TARGET")/.health-hotfix.XXXXXXXX")"
install -o root -g root -m 0600 "$TEMP" "$STAGED"
rm -f "$TEMP"
mv -f "$STAGED" "$TARGET"
cmp -s "$SRC/studio_signed_updater.py" "$TARGET" || {
  install -o root -g root -m 0600 "$BACKUP" "$TARGET"
  die "Installed byte verification failed; original restored"
}
echo "SUCCESS: Studio signed updater health-contract hotfix installed; Studio service unchanged"
echo "Initial updater backup retained under root-only updater state."
echo "The existing signed timer was resumed; future signed releases remain independently verified."
