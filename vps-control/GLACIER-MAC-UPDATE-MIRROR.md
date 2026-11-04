# Glacier Browser macOS: owner's VPS download mirror

The Mac client downloads **only** from
`https://jipite.borealos.cn/glacier-updates/` and does not need GitHub access.
The original Jipite API, Microsoft approval service, and Android update
paths are never replaced or proxied by this mirror.

## One-time VPS installation

From the VPS (NOT from an end-user Mac), using an existing or new checkout of
the public `zxasd2183-oss/comfyui-director-release` repository:

```bash
sudo apt-get install -y python3-venv
git fetch origin build/glacier-browser-macos-arm64-v0-14-1
git worktree add --detach /tmp/glacier-mac-vps origin/build/glacier-browser-macos-arm64-v0-14-1
sudo bash /tmp/glacier-mac-vps/vps-control/install-glacier-macos-updates.sh
```

Review the script before executing it. This is an intentionally guarded
deployment: it first checks the existing HTTPS Jipite Nginx configuration and
verifies an Ed25519-signed public Mac release manifest and the exact GitHub
release DMG hash. If fetching or validation fails, it does **not** change
the public Nginx routes.

The installer adds only an isolated
`/etc/nginx/snippets/glacier-macos-updates.conf` include to the existing
`jipite.borealos.cn` HTTPS virtual host. It creates a restricted
`glacierupdate` system account, a read-only Nginx static file directory,
and a 30-minute sync timer. It does not require Apple developer credentials
or the private update signing key.

## Verify from the VPS

```bash
sudo systemctl status glacier-macos-update-sync.timer --no-pager
sudo journalctl -u glacier-macos-update-sync.service -n 25 --no-pager
curl -fsS https://jipite.borealos.cn/glacier-updates/macos-arm64.json
curl -IL https://jipite.borealos.cn/glacier-updates/GlacierBrowser-v0.14.1-macOS-AppleSilicon.dmg
```

Both public URLs should give HTTP 200 and the signed manifest must show
channel `macos-arm64` and the exact DMG SHA256. The Mac client verifies
the Ed25519 signature independently; modified update metadata is rejected.

If the VPS cannot access GitHub Release assets, don't weaken verification,
disable Gatekeeper, or move the signing private key onto the VPS. Instead,
configure a GitHub Actions -> VPS SSH upload with dedicated deploy-only
credentials and a pinned SSH host key. This is a separate deployment step
and requires the owner's explicit setup.

**Important:** VPS outbound traffic may incur fees, and if serving publicly
from a mainland China VPS, verify applicable domain/hosting requirements.
The first Mac v0.14.1 crash-repair install must be manual because v0.14.0
crashes before its in-app updater can open.
