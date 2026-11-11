#!/usr/bin/env bash
# One-time, exact-match repair of the independently installed Studio root updater.
# Only fixes installation of previously absent signed code files and crash rollback.
# The Studio app, its SQLite ledger, identity, media and GPU controls are untouched.
set -Eeuo pipefail
umask 077
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 2; }
(( EUID == 0 )) || die "Root required"
(( $# == 0 )) || die "No arguments accepted"

SRC="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SRC/.." && pwd)"
TARGET=/opt/director-studio-signed-updater/studio_signed_updater.py
STATE=/var/lib/director-studio-signed-updater
PY=/opt/comfyui-director-control/.venv/bin/python
TIMER=director-studio-signed-update.timer
SERVICE=director-studio-signed-update.service
# Exact reviewed source blob from Studio PR #52, not the user-editable directory.
EXPECTED_NEW_BLOB=baffc5a0e6b37ac6022a6997ddb9058fb3a58e7d
# Confirm this exact old root script came from the audited health-contract fix.
OLD_COMMIT=615b3aeebfe16ff152e9ecf133ea8426842f1527

[[ -x "$PY" && -d "$STATE" && ! -L "$STATE" ]] || die "Existing signed updater runtime/state required"
[[ -f "$TARGET" && ! -L "$TARGET" ]] || die "Root-installed updater missing or unsafe"
[[ "$(stat -c %u "$TARGET")" == 0 && "$(stat -c %a "$TARGET")" == 600 ]] || die "Updater owner/mode invalid"
[[ -f "$STATE/installed-version.txt" && ! -L "$STATE/installed-version.txt" ]] || die "Unsafe installed-version state"
[[ "$(cat "$STATE/installed-version.txt")" == "0.9.0" ]] || die "Not the known pre-0.10.0 migration baseline"
[[ -f "$SRC/studio_signed_updater.py" && ! -L "$SRC/studio_signed_updater.py" ]] || die "Reviewed source unavailable"
[[ "$(git -C "$ROOT" branch --show-current)" == main ]] || die "Use reviewed main branch only"
git -C "$ROOT" diff --quiet -- studio/studio_signed_updater.py || die "Local updater source modified"
[[ "$(git -C "$ROOT" hash-object "$SRC/studio_signed_updater.py")" == "$EXPECTED_NEW_BLOB" ]] ||
  die "Reviewed new updater hash mismatch"
"$PY" -m py_compile "$SRC/studio_signed_updater.py"
grep -Fq 'def _restore_files(original, created):' "$SRC/studio_signed_updater.py" ||
  die "Signed-new-file rollback logic unavailable"

if cmp -s "$SRC/studio_signed_updater.py" "$TARGET"; then
  echo "SUCCESS: New-file-aware signed updater already installed"
  exit 0
fi

OLD_EXPECTED="$(mktemp "$STATE/expected-updater.XXXXXXXX")"
trap 'rm -f "$OLD_EXPECTED"' EXIT
git -C "$ROOT" show "$OLD_COMMIT:studio/studio_signed_updater.py" > "$OLD_EXPECTED" ||
  die "Known prior signed updater blob unavailable"
chmod 0600 "$OLD_EXPECTED"
cmp -s "$OLD_EXPECTED" "$TARGET" ||
  die "Installed root updater does not match the exact known health-fixed version"

systemctl is-active --quiet director-studio.service || die "Studio service must already be healthy"
systemctl is-enabled --quiet "$TIMER" || die "Signed timer must remain enabled"
systemctl stop "$TIMER"
trap 'rm -f "$OLD_EXPECTED"; systemctl start "$TIMER" >/dev/null 2>&1 || :' EXIT
if systemctl is-active --quiet "$SERVICE"; then
  die "Signed updater running concurrently; no replacement performed"
fi

BACKUP="$(mktemp "$STATE/pre-new-file-hotfix-backup.XXXXXXXX")"
cp -p "$TARGET" "$BACKUP"
chmod 0600 "$BACKUP"
STAGED="$(mktemp "$(dirname "$TARGET")/.add-files-hotfix.XXXXXXXX")"
trap 'rm -f "$OLD_EXPECTED" "$STAGED"; systemctl start "$TIMER" >/dev/null 2>&1 || :' EXIT
install -o root -g root -m 0600 "$SRC/studio_signed_updater.py" "$STAGED"
mv -f "$STAGED" "$TARGET"
if ! cmp -s "$SRC/studio_signed_updater.py" "$TARGET"; then
  install -o root -g root -m 0600 "$BACKUP" "$TARGET"
  die "Byte verification failed; previous updater restored"
fi

echo "SUCCESS: Studio signed updater now supports newly signed files with crash-safe rollback"
echo "Root-only previous updater backup retained; Studio application service unchanged."
echo "Existing signed update timer resumed; v0.10.0 channel is independently verified."
