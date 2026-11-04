#!/usr/bin/env bash
# One-time least-privilege SSH trigger setup for Glacier macOS VPS mirror.
# Does NOT modify Nginx, the existing mirror timer, or other VPS controllers.
# Run on the owner's VPS after reviewing this file.
set -euo pipefail
umask 077

if [[ "$EUID" -ne 0 ]]; then
  echo "Run with sudo on your own VPS" >&2; exit 2
fi
for cmd in ssh-keygen useradd install systemctl visudo stat; do
  command -v "$cmd" >/dev/null
done
systemctl cat glacier-macos-update-sync.service >/dev/null
systemctl is-enabled glacier-macos-update-sync.timer >/dev/null

USER_NAME=glaciertrigger
HOME_DIR=/var/lib/glacier-macos-trigger
SSH_DIR="$HOME_DIR/.ssh"
AUTH_KEYS="$SSH_DIR/authorized_keys"
KEY_DIR=/root/.config/glacier-browser
KEY_FILE="$KEY_DIR/glacier-macos-sync-trigger"
SUDOERS=/etc/sudoers.d/91-glacier-macos-sync-trigger
SUDO_CMD="/usr/bin/systemctl start glacier-macos-update-sync.service"
RULE="$USER_NAME ALL=(root) NOPASSWD: $SUDO_CMD"

echo "[1/3] Prepare a dedicated, command-restricted SSH identity"
if ! id "$USER_NAME" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$HOME_DIR" --shell /bin/sh "$USER_NAME"
fi
[[ "$(getent passwd "$USER_NAME" | cut -d: -f6)" = "$HOME_DIR" ]] || {
  echo "Existing user home differs; refusing to alter it" >&2; exit 3
}
[[ "$(getent passwd "$USER_NAME" | cut -d: -f7)" = /bin/sh ]] || {
  echo "Existing user shell differs; refusing to alter it" >&2; exit 3
}
[[ ! -L "$HOME_DIR" && ! -L "$SSH_DIR" && ! -L "$AUTH_KEYS" ]] || {
  echo "Symlink in SSH identity path; refusing" >&2; exit 3
}
install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "$HOME_DIR" "$SSH_DIR"
install -d -m 0700 -o root -g root "$KEY_DIR"
if [[ ! -f "$KEY_FILE" || ! -f "$KEY_FILE.pub" ]]; then
  [[ ! -e "$KEY_FILE" && ! -e "$KEY_FILE.pub" ]] || {
    echo "Key pair is partially missing; refusing to rotate existing key" >&2; exit 3
  }
  ssh-keygen -q -t ed25519 -a 64 -N '' -f "$KEY_FILE" -C "glacier-macos-vps-sync-only"
fi
chmod 0600 "$KEY_FILE"
chmod 0644 "$KEY_FILE.pub"
PUB="$(awk '{print $1" "$2}' "$KEY_FILE.pub")"
[[ "$PUB" == ssh-ed25519\ * ]] || {
  echo "Expected ed25519 key not found" >&2; exit 3
}

# The server forces this exact systemctl start, regardless of what the caller
# requests. 'restrict' disables port forwarding, agent forwarding and PTY.
# No arbitrary shell, package installation, or GPU/mobile approval commands.
FORCED='restrict,command="/usr/bin/sudo -n /usr/bin/systemctl start glacier-macos-update-sync.service"'
EXPECTED="$FORCED $PUB glacier-macos-sync-only"
if [[ -f "$AUTH_KEYS" ]]; then
  [[ "$(cat "$AUTH_KEYS")" = "$EXPECTED" ]] || {
    echo "authorized_keys differs; refusing to overwrite existing SSH authorizations" >&2
    exit 3
  }
else
  printf '%s\n' "$EXPECTED" > "$AUTH_KEYS"
fi
chown "$USER_NAME:$USER_NAME" "$AUTH_KEYS"
chmod 0600 "$AUTH_KEYS"

echo "[2/3] Add exact-command sudo permission only"
if [[ -e "$SUDOERS" ]]; then
  [[ "$(cat "$SUDOERS")" = "$RULE" ]] || {
    echo "Unexpected existing sudoers rule; refusing overwrite" >&2; exit 3
  }
else
  TMP="$(mktemp /etc/sudoers.d/.glacier-macos.XXXXXX)"
  trap 'rm -f "$TMP"' EXIT
  printf '%s\n' "$RULE" > "$TMP"
  chmod 0440 "$TMP"
  visudo -cf "$TMP" >/dev/null
  mv "$TMP" "$SUDOERS"
  trap - EXIT
fi
visudo -cf "$SUDOERS" >/dev/null
sudo -n -u "$USER_NAME" sudo -n /usr/bin/systemctl show   glacier-macos-update-sync.service --property=LoadState >/dev/null 2>&1 || true
echo "[3/3] Key generation and forced-command authorization complete"
echo
echo "GitHub Actions repository secrets to set in Settings > Secrets and variables > Actions:"
echo "  GLACIER_VPS_SSH_PRIVATE_KEY = contents of $KEY_FILE"
echo "  GLACIER_VPS_SSH_HOST        = VPS SSH hostname/IP (not the HTTPS Cloudflare proxy)"
echo "  GLACIER_VPS_SSH_KNOWN_HOSTS = '<host> ssh-ed25519 <BASE64>'"
echo "  GLACIER_VPS_SSH_PORT        = SSH port, optional (defaults to 22)"
echo
echo "Read the pinned host public key LOCALLY, not from ssh-keyscan over an untrusted network:"
echo "  sudo cat /etc/ssh/ssh_host_ed25519_key.pub"
echo "Verify its SHA256 fingerprint by a trusted path:"
echo "  sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256"
echo
echo "Never share the private key in ChatGPT or commit it to GitHub."
echo "After configuring the GitHub secret, remove the local private key copy"
echo "only once a manual trigger test has succeeded; keep the .pub and authorized_keys."
echo "The VPS update timer and all existing API services remain unchanged."
