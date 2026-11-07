#!/usr/bin/env bash
# Install the V0.7 offline-first video CLI into a chosen persistent GPU directory.
# Does NOT connect to ComfyUI, submit any prompts, start GPU, open ports or
# change the existing Director Hub, mobile approvals, SSH or power services.
set -Eeuo pipefail
umask 077
fail() { echo "ERROR: $*" >&2; exit 2; }
(( $# == 1 )) || fail "Usage: bash video-pipeline/install-on-gpu.sh /absolute/persistent/directory"
TARGET="$1"
[[ "$TARGET" == /* && "$TARGET" != "/" ]] || fail "Require an absolute persistent directory, not /"
[[ "$TARGET" != *"/../"* && "$TARGET" != *"/./"* ]] || fail "Unsafe destination"
SRC="$(cd "$(dirname "$0")" && pwd)"
[[ -f "$SRC/director_video.py" && ! -L "$SRC/director_video.py" ]] || fail "Trusted local source missing"
[[ -f "$SRC/studio_return_client.py" && ! -L "$SRC/studio_return_client.py" ]] || fail "Return client source missing"
command -v python3 >/dev/null || fail "Python 3 is required"
python3 -m py_compile "$SRC/director_video.py" "$SRC/studio_return_client.py"
python3 -m unittest discover -s "$SRC/tests" -p "test_*.py" -q
[[ ! -L "$TARGET" ]] || fail "Installation destination cannot be a symlink"
mkdir -p "$TARGET"
[[ -d "$TARGET" && ! -L "$TARGET" ]] || fail "Invalid installation destination"
if [[ -e "$TARGET/director_video.py" || -L "$TARGET/director_video.py" ]]; then
    [[ -f "$TARGET/director_video.py" && ! -L "$TARGET/director_video.py" ]] \
        || fail "Existing installation is not a regular file"
    backup="$TARGET/director_video.py.backup.$(date -u +%Y%m%d%H%M%S)"
    [[ ! -e "$backup" ]] || fail "Backup collision; retry later"
    cp -p "$TARGET/director_video.py" "$backup"
    chmod 0600 "$backup"
    echo "Previous local runner backed up"
fi
install -m 0700 "$SRC/director_video.py" "$TARGET/.director_video.py.new"
mv -f "$TARGET/.director_video.py.new" "$TARGET/director_video.py"
install -m 0700 "$SRC/studio_return_client.py" "$TARGET/studio_return_client.py"
install -m 0600 "$SRC/README.md" "$TARGET/README.md"
echo "PASS: video runner installed into the chosen persistent directory"
echo "This installer made ZERO network, GPU generation or cloud power requests"
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
    echo "NOTE: install ffmpeg/ffprobe before using assemble; prepare and inspect work without them"
fi
echo "Next: python3 $TARGET/director_video.py inspect --workflow H3_EXPORTED_API.json"
