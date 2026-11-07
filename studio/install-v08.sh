#!/usr/bin/env bash
# Installs a private Studio web UI on VPS loopback ONLY, port 8900.
# Does not modify Nginx, Hub, phone approvals, GPU or power credentials.
set -Eeuo pipefail
umask 077
die(){ echo "ERROR: $*" >&2; exit 2; }
[[ "$EUID" -eq 0 ]] || die "Run with sudo on owner VPS"
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/director-studio
[[ -f "$SRC/studio_core.py" && ! -L "$SRC/studio_core.py" ]] || die "Missing trusted studio sources"
for file in gpu_return.py gpu_power_bridge.py studio_server.py studio_identity.py session_store.py studio_brain.py studio_backend.py studio_core.py production_core.py production_web.py production_manage.py visual_library.py character_library.py character_library_v2.py shot_character_bindings.py scene_library.py production_workflows.py video_results.py picture_cuts.py picture_cut_jobs.py audio_stems.py audio_master.py audio_master_jobs.py subtitle_tracks.py release_candidates.py release_jobs.py assemble_approved_cut.py manage.py index.html login.html login.css studio.css studio.js glacier-peaks.svg glacier-banner.svg director-studio.service; do
  [[ -f "$SRC/$file" && ! -L "$SRC/$file" ]] || die "Missing source $file"
done
systemctl is-active --quiet director-hub-mcp || die "Existing Director Hub must be running"
[[ -x /usr/bin/python3 ]] || die "Python3 required"
python3 -m py_compile "$SRC"/gpu_return.py "$SRC"/gpu_power_bridge.py "$SRC"/studio_*.py "$SRC"/production_*.py "$SRC"/visual_library.py "$SRC"/character_library.py "$SRC"/character_library_v2.py "$SRC"/shot_character_bindings.py "$SRC"/scene_library.py "$SRC"/production_workflows.py "$SRC"/session_store.py "$SRC"/manage.py
python3 -m unittest discover -s "$SRC/tests" -p "test_*.py" -q
if ! id directorstudio >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin directorstudio
fi
[[ ! -L "$DEST" ]] || die "Destination cannot be symlink"
install -d -o root -g root -m 0755 "$DEST"
for file in gpu_return.py gpu_power_bridge.py studio_server.py studio_identity.py session_store.py studio_brain.py studio_backend.py studio_core.py production_core.py production_web.py production_manage.py visual_library.py character_library.py character_library_v2.py shot_character_bindings.py scene_library.py production_workflows.py video_results.py picture_cuts.py picture_cut_jobs.py audio_stems.py audio_master.py audio_master_jobs.py subtitle_tracks.py release_candidates.py release_jobs.py assemble_approved_cut.py manage.py index.html login.html login.css studio.css studio.js glacier-peaks.svg glacier-banner.svg; do
    install -o root -g root -m 0644 "$SRC/$file" "$DEST/$file"
done
install -o root -g root -m 0644 "$SRC/director-studio.service" \
  /etc/systemd/system/director-studio.service
systemctl daemon-reload
systemctl enable --now director-studio
systemctl restart director-studio
systemctl is-active --quiet director-studio || die "Studio service failed"
python3 - <<'PY'
import json,urllib.request
url="http://127.0.0.1:8900/api/v1/snapshot"
for attempt in range(12):
  try:
    with urllib.request.urlopen(url,timeout=3) as response:
      data=json.load(response)
    if data.get("mode")!="operator_ledger_only" or "live" not in data:
      raise RuntimeError("Unexpected Studio response")
    print("PASS: Studio 8900 loopback JSON + live Hub status cache")
    break
  except Exception:
    if attempt==11: raise
    import time
    time.sleep(1)
PY
echo "SUCCESS: Director Studio V0.9 production foundation active on VPS loopback :8900"
echo "NOT exposed by Nginx. Use an authenticated SSH local-forward on your computer:"
echo "  ssh -N -L 8900:127.0.0.1:8900 YOUR_VPS_SSH_ALIAS"
echo "Then open http://127.0.0.1:8900 in your local browser."
echo "GPU and power approvals unaffected; no jobs submitted."
