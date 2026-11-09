# Glacier Browser preview installers on owner VPS (111.230.226.74)

**Contract:** GitHub Actions builds and releases signed/hash-checked package
assets; the VPS fetches those public release assets and verifies each
SHA-256 against the immutable GitHub release sidecar; **client update
discovery and package download use only owner's VPS HTTPS origin**, not
GitHub. This preview channel is **manual install only** and is NOT a
replacement for independently Ed25519-signed production updates.

## Current production host structure

- Origin: https://sync.borealos.cn
- Existing six-domain TLS on the VPS :8443, unchanged.
- Existing Glacier account API: 127.0.0.1:18991, unchanged.
- Existing sync TLS snippet: /etc/nginx/snippets/glacier-sync.conf
- Preview-only static snippet: /etc/nginx/snippets/glacier-preview-downloads.conf
- Unprivileged sync user: glacierpreview
- Files: /var/lib/glacier-preview-downloads; no credentials or private keys.
- Timer: glacier-preview-update-sync.timer, every 30 minutes as recovery.
- Production Mac signed mirror on jipite.borealos.cn remains unchanged.

## Deploy (once)

Obtain the **latest** branch `fix/glacier-browser-windows-v0201-input` on
the VPS in a temporary detached worktree (no effect on existing main):

```bash
cd ~/comfyui-director-release
git fetch origin fix/glacier-browser-windows-v0201-input
git worktree add --detach ~/glacier-preview-vps origin/fix/glacier-browser-windows-v0201-input
sudo bash ~/glacier-preview-vps/vps-control/install-glacier-preview-downloads.sh
git worktree remove ~/glacier-preview-vps
```

The install script first downloads and SHA-256 verifies the Windows EXE and
Mac DMG **on the VPS**. If either cannot be fetched or verified, the script
will refuse to activate the public paths. It then adds only one include to
the pre-existing Glacier Sync **API snippet**; it never rewrites a domain
server block. It runs `nginx -t`, rolls back an invalid edit and checks the
VPS public manifests. The account API and other five domains must remain
unaffected.

Verify:

```bash
curl -fsS https://sync.borealos.cn/health
curl -fsS https://sync.borealos.cn/downloads/windows-preview.json
curl -fsS https://sync.borealos.cn/downloads/macos-arm64-preview.json
curl -IL https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.4-Windows-Setup-x64.exe
```

The package URL above is illustrative until GitHub has actually published
that exact version, the VPS mirror has fetched it, and it returns HTTP 200.

The source release ZIP is **not** served to clients and the preview metadata
cannot authorize an unattended update. If the VPS cannot reach GitHub,
deploy-only GitHub Actions uploads with short-lived OIDC must be configured
as a separate option; never store release signing keys on the VPS.

**Known remaining formal-channel boundary:** Windows stable Ed25519 manifests
still encode the original signed GitHub asset URL. Moving that signed
channel to the VPS requires generating a **new** correctly signed manifest
with the owner's offline Ed25519 private key. Do not silently rewrite
signed fields or bypass signature verification.
