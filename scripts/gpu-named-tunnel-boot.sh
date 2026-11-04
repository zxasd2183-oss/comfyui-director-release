#!/usr/bin/env bash
# GPU-side boot hook for CompShare containers.
# Place in /start.d/90-comfyui-director-v3.sh (provider runs at container boot).
# No GPU cloud power API calls; no ComfyUI job submission; never starts a
# second ComfyUI process. Requires user-configured named Cloudflare Tunnel.
set -euo pipefail
umask 077
CONFIG_DIR=/etc/comfyui-director
TOKEN_FILE="$CONFIG_DIR/gpu-named-tunnel.token"
HOME_FILE="$CONFIG_DIR/installed-home"
PID_FILE=/run/comfyui-director-named-tunnel.pid
LOG_FILE=/var/log/comfyui-director-named-tunnel.log
[[ -r "$TOKEN_FILE" && -r "$HOME_FILE" ]] || {
  echo "Director boot: required named tunnel configuration missing" >&2
  exit 2
}
DIRECTOR_HOME="$(cat "$HOME_FILE")"
[[ "$DIRECTOR_HOME" == /* && -f "$DIRECTOR_HOME/.comfyui-director/config.json" ]] || {
  echo "Director boot: prior Director installation missing; nothing installed" >&2
  exit 3
}
DIRECTOR_ROOT="$DIRECTOR_HOME/.comfyui-director"
START_SCRIPT="$DIRECTOR_ROOT/controller/start.sh"
[[ -f "$START_SCRIPT" && ! -L "$START_SCRIPT" ]] || {
  echo "Director boot: installed Supervisor start.sh not found" >&2
  exit 4
}

# Do not touch Slink 8765. Use the existing Director V3 8790 only.
healthy() {
  python3 - <<'PY'
import json
from urllib.request import urlopen
try:
    with urlopen("http://127.0.0.1:8790/health", timeout=3) as response:
        result=json.load(response)
    raise SystemExit(0 if result.get("ok") is True and
                     result.get("version") == "0.3.0" else 1)
except Exception:
    raise SystemExit(1)
PY
}
if healthy; then
  echo "Director boot: existing Director V3 is healthy"
else
  echo "Director boot: invoking previously installed V3 supervisor"
  (cd "$DIRECTOR_ROOT/controller" && bash "$START_SCRIPT") >/dev/null 2>&1 || :
fi

# Validate cloudflared supports --token-file. Requires v2025.4.0+.
command -v cloudflared >/dev/null || {
  echo "Director boot: cloudflared missing; no tunnel started" >&2
  exit 5
}
if [[ -s "$PID_FILE" ]]; then
  prior_pid="$(cat "$PID_FILE")"
  if [[ "$prior_pid" =~ ^[0-9]+$ ]] && kill -0 "$prior_pid" 2>/dev/null; then
    echo "Director boot: named tunnel already running"
    exit 0
  fi
fi
# No bearer token in process arguments, logs or standard output.
nohup cloudflared tunnel --no-autoupdate run --token-file "$TOKEN_FILE" \
  >> "$LOG_FILE" 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" > "$PID_FILE"
sleep 2
if ! kill -0 "$pid" 2>/dev/null; then
  echo "Director boot: named tunnel failed, check private local log" >&2
  exit 6
fi
echo "Director boot: named tunnel started; stable Cloudflare hostname unchanged"
if ! healthy; then
  echo "Director boot: V3 not yet healthy; check local Supervisor log" >&2
fi
echo "Director boot: does not start ComfyUI or any video generation"
