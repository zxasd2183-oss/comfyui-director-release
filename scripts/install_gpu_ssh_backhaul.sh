#!/usr/bin/env bash
# Install a persistent GPU outbound SSH reverse tunnel on an existing CompShare
# container. Does NOT create keys, trust VPS host keys, open public GPU ports,
# operate GPU power or submit ComfyUI jobs. All SSH enrollment remains local.
set -euo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "Run as GPU container root" >&2; exit 2; }
ROOT="/root/.comfyui-director"
DIR="/root/.ssh"
CFG="$DIR/director_backhaul_config"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
[[ -f "$ROOT/config.json" ]] || { echo "Existing installed V3 missing" >&2; exit 2; }
[[ -f "$CFG" && ! -L "$CFG" && "$(stat -c '%a' "$CFG")" == 600 ]] || {
 echo "Expected private 0600 SSH client config at $CFG" >&2; exit 2;
}
command -v ssh >/dev/null || { echo "Install openssh-client first" >&2; exit 2; }
command -v flock >/dev/null || { echo "Install util-linux first" >&2; exit 2; }
[[ -f "$SCRIPT_DIR/gpu-ssh-backhaul.sh" ]] || { echo "Backhaul source missing" >&2; exit 2; }
# Effective SSH options must not permit accepting unknown VPS SSH host keys.
options="$(ssh -G -F "$CFG" director-backhaul 2>/dev/null)" || {
 echo "SSH config has errors" >&2; exit 3;
}
printf '%s\n' "$options" | grep -qx 'user directorlink' || {
 echo "SSH alias must use dedicated directorlink account" >&2; exit 3;
}
printf '%s\n' "$options" | grep -Eq '^stricthostkeychecking (yes|true)
 echo "Pin VPS SSH host key and set StrictHostKeyChecking yes" >&2; exit 3;
}
printf '%s\n' "$options" | grep -Eq '^batchmode (yes|true)
 echo "BatchMode must be yes for unattended startup" >&2; exit 3;
}
printf '%s\n' "$options" | grep -Eq '^userknownhostsfile /root/.ssh/director_backhaul_known_hosts($| )' || {
 echo "Use a separate trusted VPS known-hosts file" >&2; exit 3;
}
KNOWN="$DIR/director_backhaul_known_hosts"
[[ -s "$KNOWN" && ! -L "$KNOWN" ]] || {
 echo "Trusted VPS known-hosts file missing: verify fingerprint first" >&2; exit 3;
}
[[ -f "$DIR/director_backhaul_ed25519" && ! -L "$DIR/director_backhaul_ed25519" ]] || {
 echo "Dedicated GPU private SSH key missing" >&2; exit 3;
}
if [[ -e /start.d/90-director-gpu-backhaul.sh ]]; then
 echo "Existing /start.d/90-director-gpu-backhaul.sh left unchanged" >&2
 echo "Review it manually if reinstalling." >&2
 exit 4
fi
install -o root -g root -m 0750 "$SCRIPT_DIR/gpu-ssh-backhaul.sh" \
 /usr/local/sbin/director-gpu-ssh-backhaul
install -d -o root -g root -m 0755 /start.d
cat > /start.d/90-director-gpu-backhaul.sh <<'EOF'
#!/usr/bin/env bash
# CompShare /start.d auto-launch, no secrets or GPU power operations.
/usr/local/sbin/director-gpu-ssh-backhaul --launch
EOF
chown root:root /start.d/90-director-gpu-backhaul.sh
chmod 0750 /start.d/90-director-gpu-backhaul.sh
echo "Installed /start.d/90-director-gpu-backhaul.sh for next GPU boot."
echo "To test now, on the GPU: bash /start.d/90-director-gpu-backhaul.sh"
echo "The VPS must already have the dedicated restricted SSH user/key."
echo "This installer did NOT power the GPU on/off or change ComfyUI jobs."
 || {
 echo "Pin VPS SSH host key and set StrictHostKeyChecking yes" >&2; exit 3;
}
printf '%s\n' "$options" | grep -qx 'batchmode yes' || {
 echo "BatchMode must be yes for unattended startup" >&2; exit 3;
}
printf '%s\n' "$options" | grep -q '^userknownhostsfile /root/.ssh/director_backhaul_known_hosts$' || {
 echo "Use a separate trusted VPS known-hosts file" >&2; exit 3;
}
KNOWN="$DIR/director_backhaul_known_hosts"
[[ -s "$KNOWN" && ! -L "$KNOWN" ]] || {
 echo "Trusted VPS known-hosts file missing: verify fingerprint first" >&2; exit 3;
}
[[ -f "$DIR/director_backhaul_ed25519" && ! -L "$DIR/director_backhaul_ed25519" ]] || {
 echo "Dedicated GPU private SSH key missing" >&2; exit 3;
}
if [[ -e /start.d/90-director-gpu-backhaul.sh ]]; then
 echo "Existing /start.d/90-director-gpu-backhaul.sh left unchanged" >&2
 echo "Review it manually if reinstalling." >&2
 exit 4
fi
install -o root -g root -m 0750 "$SCRIPT_DIR/gpu-ssh-backhaul.sh" \
 /usr/local/sbin/director-gpu-ssh-backhaul
install -d -o root -g root -m 0755 /start.d
cat > /start.d/90-director-gpu-backhaul.sh <<'EOF'
#!/usr/bin/env bash
# CompShare /start.d auto-launch, no secrets or GPU power operations.
/usr/local/sbin/director-gpu-ssh-backhaul --launch
EOF
chown root:root /start.d/90-director-gpu-backhaul.sh
chmod 0750 /start.d/90-director-gpu-backhaul.sh
echo "Installed /start.d/90-director-gpu-backhaul.sh for next GPU boot."
echo "To test now, on the GPU: bash /start.d/90-director-gpu-backhaul.sh"
echo "The VPS must already have the dedicated restricted SSH user/key."
echo "This installer did NOT power the GPU on/off or change ComfyUI jobs."
 || {
 echo "BatchMode must be yes for unattended startup" >&2; exit 3;
}
printf '%s\n' "$options" | grep -q '^userknownhostsfile /root/.ssh/director_backhaul_known_hosts$' || {
 echo "Use a separate trusted VPS known-hosts file" >&2; exit 3;
}
KNOWN="$DIR/director_backhaul_known_hosts"
[[ -s "$KNOWN" && ! -L "$KNOWN" ]] || {
 echo "Trusted VPS known-hosts file missing: verify fingerprint first" >&2; exit 3;
}
[[ -f "$DIR/director_backhaul_ed25519" && ! -L "$DIR/director_backhaul_ed25519" ]] || {
 echo "Dedicated GPU private SSH key missing" >&2; exit 3;
}
if [[ -e /start.d/90-director-gpu-backhaul.sh ]]; then
 echo "Existing /start.d/90-director-gpu-backhaul.sh left unchanged" >&2
 echo "Review it manually if reinstalling." >&2
 exit 4
fi
install -o root -g root -m 0750 "$SCRIPT_DIR/gpu-ssh-backhaul.sh" \
 /usr/local/sbin/director-gpu-ssh-backhaul
install -d -o root -g root -m 0755 /start.d
cat > /start.d/90-director-gpu-backhaul.sh <<'EOF'
#!/usr/bin/env bash
# CompShare /start.d auto-launch, no secrets or GPU power operations.
/usr/local/sbin/director-gpu-ssh-backhaul --launch
EOF
chown root:root /start.d/90-director-gpu-backhaul.sh
chmod 0750 /start.d/90-director-gpu-backhaul.sh
echo "Installed /start.d/90-director-gpu-backhaul.sh for next GPU boot."
echo "To test now, on the GPU: bash /start.d/90-director-gpu-backhaul.sh"
echo "The VPS must already have the dedicated restricted SSH user/key."
echo "This installer did NOT power the GPU on/off or change ComfyUI jobs."
 || {
 echo "Pin VPS SSH host key and set StrictHostKeyChecking yes" >&2; exit 3;
}
printf '%s\n' "$options" | grep -qx 'batchmode yes' || {
 echo "BatchMode must be yes for unattended startup" >&2; exit 3;
}
printf '%s\n' "$options" | grep -q '^userknownhostsfile /root/.ssh/director_backhaul_known_hosts$' || {
 echo "Use a separate trusted VPS known-hosts file" >&2; exit 3;
}
KNOWN="$DIR/director_backhaul_known_hosts"
[[ -s "$KNOWN" && ! -L "$KNOWN" ]] || {
 echo "Trusted VPS known-hosts file missing: verify fingerprint first" >&2; exit 3;
}
[[ -f "$DIR/director_backhaul_ed25519" && ! -L "$DIR/director_backhaul_ed25519" ]] || {
 echo "Dedicated GPU private SSH key missing" >&2; exit 3;
}
if [[ -e /start.d/90-director-gpu-backhaul.sh ]]; then
 echo "Existing /start.d/90-director-gpu-backhaul.sh left unchanged" >&2
 echo "Review it manually if reinstalling." >&2
 exit 4
fi
install -o root -g root -m 0750 "$SCRIPT_DIR/gpu-ssh-backhaul.sh" \
 /usr/local/sbin/director-gpu-ssh-backhaul
install -d -o root -g root -m 0755 /start.d
cat > /start.d/90-director-gpu-backhaul.sh <<'EOF'
#!/usr/bin/env bash
# CompShare /start.d auto-launch, no secrets or GPU power operations.
/usr/local/sbin/director-gpu-ssh-backhaul --launch
EOF
chown root:root /start.d/90-director-gpu-backhaul.sh
chmod 0750 /start.d/90-director-gpu-backhaul.sh
echo "Installed /start.d/90-director-gpu-backhaul.sh for next GPU boot."
echo "To test now, on the GPU: bash /start.d/90-director-gpu-backhaul.sh"
echo "The VPS must already have the dedicated restricted SSH user/key."
echo "This installer did NOT power the GPU on/off or change ComfyUI jobs."
