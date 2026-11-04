# Glacier Browser macOS: immediate VPS update trigger

The workflow `.github/workflows/glacier-macos-vps-immediate.yml` runs on **each
new offline-signed** `channels/macos-arm64.json` commit. It verifies the
embedded Ed25519 signature, then requests exactly one permitted command on
the owner's VPS. That service independently downloads and authenticates
the DMG, and the workflow confirms HTTPS is serving the signed manifest.
The existing 30-minute systemd timer remains as a fallback.

**This requires one-time, owner-controlled SSH secret setup.**
The GitHub connector and Director VPS status tools cannot configure VPS
SSH or GitHub Secrets. Until this is done, the workflow intentionally fails
with a missing-secret error instead of pretending the update was delivered.

## 1. Bootstrap on the already-configured VPS (one time)

Review `vps-control/install-glacier-macos-immediate-trigger.sh` first.

If an existing repository checkout is at `~/glacier-mac-vps-setup`:

```bash
cd ~/glacier-mac-vps-setup
git fetch origin glacier-browser-updates
git show origin/glacier-browser-updates:vps-control/install-glacier-macos-immediate-trigger.sh > /tmp/install-glacier-macos-immediate-trigger.sh
less /tmp/install-glacier-macos-immediate-trigger.sh
sudo bash /tmp/install-glacier-macos-immediate-trigger.sh
```

This creates a dedicated `glaciertrigger` SSH account. The authorized
public key is constrained with OpenSSH `restrict,command=...` to one exact
systemd invocation: `sudo -n /usr/bin/systemctl start glacier-macos-update-sync.service`.
The matching sudoers rule allows only this command. It does not grant root
shell, Nginx configuration or approval/GPU permissions.

A private Ed25519 SSH key is initially generated at
`/root/.config/glacier-browser/glacier-macos-sync-trigger`. Keep it private,
do not upload the file to the repository, and do not paste it into chat.
This is an **SSH trigger key**, NOT the offline Ed25519 release-signing key.

## 2. Configure GitHub repository Actions secrets

At
`https://github.com/zxasd2183-oss/comfyui-director-release/settings/secrets/actions`,
add:

- `GLACIER_VPS_SSH_PRIVATE_KEY`: contents of the generated private SSH key.
- `GLACIER_VPS_SSH_HOST`: actual public SSH hostname/IP of VPS; Cloudflare
  HTTPS hostname is not always an SSH endpoint.
- `GLACIER_VPS_SSH_KNOWN_HOSTS`: trusted OpenSSH known_hosts line with the
  VPS Ed25519 SSH host public key from `/etc/ssh/ssh_host_ed25519_key.pub`.
  Format: `<host> ssh-ed25519 <base64-public-key>`; for non-22 SSH port,
  format: `[<host>]:<port> ssh-ed25519 <base64-public-key>`.
  Obtain the fingerprint using a **trusted SSH console** and verify it
  independently. Do **not** accept an unauthenticated `ssh-keyscan` value.
- `GLACIER_VPS_SSH_PORT`: optional, defaults to 22.

The private key can be retrieved locally while administering the VPS with
`sudo cat /root/.config/glacier-browser/glacier-macos-sync-trigger`.
Do not copy or paste it into issues, chat, workflow logs or shell scripts.

Check that inbound SSH from GitHub-hosted Actions is permitted by the VPS
firewall and provider. Restrict the `glaciertrigger` account as tightly as
the server's SSH configuration allows.

## 3. Run and verify

Push the next signed `channels/macos-arm64.json` change or run the
immediate workflow manually on branch `glacier-browser-updates`.
The run must show:

1. Valid Ed25519 manifest.
2. Restricted SSH trigger completed.
3. Public VPS serves the **exact** signed manifest.
4. Mac DMG is available over VPS HTTPS with expected length.

The Mac update URL remains
`https://jipite.borealos.cn/glacier-updates/macos-arm64.json`.
No Mac client needs GitHub access.

If SSH is not reachable or the VPS cannot fetch a GitHub release,
the workflow fails visibly; the existing systemd timer continues working.
Never bypass Ed25519 or SHA256 checks to hide a deployment failure.

Once an authenticated Actions test succeeds, remove the **temporary VPS
private-key copy** only after retaining a secure backup or verifying the
GitHub Actions secret is correctly stored. The VPS keeps only the public
authorized key. Rotate the SSH secret immediately if exposed.

**Note:** The automatic trigger occurs when the signed update manifest is
published, not simply when a macOS .dmg finishes compiling, because only
the former constitutes an authenticated release.
