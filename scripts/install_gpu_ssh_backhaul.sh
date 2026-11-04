#!/usr/bin/env bash
# Install only the pre-existing Director V3 GPU SSH backhaul boot hook.
# The GPU private key, trusted host fingerprint and VPS restricted account
# MUST have been configured independently before running this installer.
# No GPU power, ComfyUI jobs, DNS or external credentials are changed.
set -euo pipefail
umask 077

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 2; }
[[ "$EUID" -eq 0 ]] || fail "Run as GPU container root"

ROOT="/root/.comfyui-director"
CFG="/root/.ssh/director_backhaul_config"
KNOWN="/root/.ssh/director_backhaul_known_hosts"
KEY="/root/.ssh/director_backhaul_ed25519"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE="$SCRIPT_DIR/gpu-ssh-backhaul.sh"
DEST="/usr/local/sbin/director-gpu-ssh-backhaul"
HOOK="/start.d/90-director-gpu-backhaul.sh"

[[ -f "$ROOT/config.json" && ! -L "$ROOT/config.json" ]] || fail "Installed Director V3 config missing"
[[ -f "$ROOT/controller/start.sh" && ! -L "$ROOT/controller/start.sh" ]] || fail "Installed V3 supervisor missing"
[[ -f "$SOURCE" && ! -L "$SOURCE" ]] || fail "GPU SSH backhaul runtime script missing"
[[ -f "$CFG" && ! -L "$CFG" ]] || fail "Dedicated SSH config missing"
[[ "$(stat -c '%a' "$CFG")" == "600" ]] || fail "SSH config must have mode 0600"
[[ -s "$KNOWN" && ! -L "$KNOWN" ]] || fail "Verify VPS host fingerprint; trusted known_hosts file missing"
[[ -s "$KEY" && ! -L "$KEY" ]] || fail "Dedicated GPU private key missing"
[[ "$(stat -c '%a' "$KEY")" == "600" ]] || fail "SSH private key must have mode 0600"
command -v ssh >/dev/null || fail "OpenSSH client is missing"
command -v flock >/dev/null || fail "flock command is missing"
bash -n "$SOURCE" || fail "GPU SSH runtime script contains invalid Bash syntax"

python3 - "$ROOT/config.json" <<'PY' || fail "Expected existing Director V3 on local port 8790"
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert type(config.get("port")) is int and config["port"] == 8790
assert isinstance(config.get("mcp_path"), str) and config["mcp_path"].startswith("/mcp/")
PY

# ssh -G reads the local effective alias, without connecting to the VPS.
options="$(ssh -G -F "$CFG" director-backhaul 2>/dev/null)" || fail "Invalid SSH backhaul client configuration"
option() { awk -v wanted="$1" '$1 == wanted { $1=""; sub(/^[[:space:]]+/, ""); print; exit }' <<< "$options"; }
[[ "$(option user)" == "directorlink" ]] || fail "SSH must use dedicated directorlink user"
case "$(option stricthostkeychecking)" in yes|true) ;; *) fail "StrictHostKeyChecking must be yes" ;; esac
case "$(option batchmode)" in yes|true) ;; *) fail "BatchMode must be yes" ;; esac
case "$(option exitonforwardfailure)" in yes|true) ;; *) fail "ExitOnForwardFailure must be yes" ;; esac
[[ "$(option userknownhostsfile)" == "$KNOWN" ]] || fail "Use dedicated verified VPS known_hosts path"
[[ "$(option identityfile)" == "$KEY" ]] || fail "Use dedicated backhaul private key"

# Protect any previously deployed hook against accidental overwrites.
if [[ -e "$HOOK" || -L "$HOOK" ]]; then
    echo "Existing GPU /start.d hook preserved. Nothing was overwritten."
    echo "Your manually installed working backhaul does not need reinstalling."
    exit 0
fi

install -d -o root -g root -m 0755 /usr/local/sbin /start.d
install -o root -g root -m 0750 "$SOURCE" "$DEST"
cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
# CompShare /start.d launches a local outbound SSH reconnect watcher only.
exec /usr/local/sbin/director-gpu-ssh-backhaul --launch
EOF
chown root:root "$HOOK"
chmod 0750 "$HOOK"
bash -n "$HOOK"
echo "SUCCESS: GPU SSH backhaul boot hook installed."
echo "Test it locally: bash /start.d/90-director-gpu-backhaul.sh"
echo "No GPU provider power, DNS, or ComfyUI jobs were changed."
