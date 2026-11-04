#!/usr/bin/env bash
# Rented CompShare GPU -> owner VPS outbound SSH reverse tunnel.
# No Cloudflare, no GPU provider power APIs, no ComfyUI job submission.
# Intended to run as a root-owned CompShare /start.d hook and persistently
# retry SSH ONLY after the already-installed local Director V3 is healthy.
set -euo pipefail
umask 077

SCRIPT="/usr/local/sbin/director-gpu-ssh-backhaul"
CONFIG="/root/.ssh/director_backhaul_config"
ROOT="/root/.comfyui-director"
START="$ROOT/controller/start.sh"
LOCK="/run/director-gpu-ssh-backhaul.lock"
LOG="/var/log/director-gpu-ssh-backhaul.log"

healthy() {
  python3 - <<'PY'
import json
from urllib.request import urlopen
try:
    with urlopen("http://127.0.0.1:8790/health", timeout=3) as response:
        data=json.load(response)
    raise SystemExit(0 if isinstance(data,dict) and data.get("ok") is True and
                     data.get("version") == "0.3.0" else 1)
except Exception:
    raise SystemExit(1)
PY
}

check_prereqs() {
  [[ "$EUID" -eq 0 ]] || { echo "Run as root inside the GPU container" >&2; return 2; }
  command -v ssh >/dev/null || { echo "OpenSSH client not installed" >&2; return 2; }
  command -v flock >/dev/null || { echo "flock command not installed" >&2; return 2; }
  [[ -f "$CONFIG" && ! -L "$CONFIG" ]] || { echo "Backhaul SSH config missing" >&2; return 2; }
  [[ "$(stat -c '%a' "$CONFIG")" == "600" ]] || { echo "Backhaul SSH config must be 0600" >&2; return 2; }
  [[ -f "$ROOT/config.json" && -f "$START" && ! -L "$START" ]] || {
    echo "Existing V3 installation /start.sh missing; aborting" >&2; return 2;
  }
  local port
  port="$(python3 - "$ROOT/config.json" <<'PY'
import json,sys
try:
    config=json.load(open(sys.argv[1],encoding="utf-8"))
    if config.get("port") == 8790 and isinstance(config.get("mcp_path"),str):
        print("8790")
except Exception:
    pass
PY
)"
  [[ "$port" == "8790" ]] || { echo "Director V3 must use localhost 8790; Slink 8765 untouched" >&2; return 2; }
}

launch_once() {
  check_prereqs
  [[ -x "$SCRIPT" ]] || { echo "Install backhaul script first" >&2; return 2; }
  if [[ ! -e "$LOG" ]]; then
    install -o root -g root -m 0600 /dev/null "$LOG"
  fi
  nohup "$SCRIPT" --foreground >> "$LOG" 2>&1 < /dev/null &
  echo "GPU: SSH reverse-backhaul watcher launched; PID=$! (private local log: $LOG)"
}

run_foreground() {
  check_prereqs
  exec 9>"$LOCK"
  if ! flock -n 9; then
    echo "Another GPU SSH backhaul watcher already holds the lock"
    exit 0
  fi
  if healthy; then
    echo "Director V3 on localhost 8790 already healthy"
  else
    echo "Starting existing Director V3 supervisor, not ComfyUI"
    # Never run an arbitrary downloaded replacement. This is the preinstalled start.sh.
    (cd "$ROOT/controller" && bash "$START") >/dev/null 2>&1 || true
  fi
  while :; do
    if healthy; then
      echo "Connecting outbound restricted SSH reverse port to owner VPS"
      # SSH identity and verified VPS host key come from the local root-only config.
      # No credentials appear on the command line or in the GitHub repository.
      ssh -F "$CONFIG" -NT \
        -o BatchMode=yes -o StrictHostKeyChecking=yes \
        -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
        -R 127.0.0.1:18790:127.0.0.1:8790 \
        director-backhaul || true
      echo "Backhaul disconnected; will reconnect"
    else
      echo "Director V3 not yet healthy; retrying without spawning a second server"
    fi
    sleep 10
  done
}

mode="--launch"
if (( $# > 0 )); then mode="$1"; fi
case "$mode" in
  --launch) launch_once ;;
  --foreground) run_foreground ;;
  --check)
    check_prereqs
    if healthy; then echo "Director V3 healthy"; else echo "Director V3 currently offline"; fi
    echo "GPU backhaul prerequisites OK; VPS host key / SSH login require live verification"
    ;;
  *) echo "Usage: $0 [--launch|--foreground|--check]" >&2; exit 2 ;;
esac
