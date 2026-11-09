# Glacier unified signed-release VPS mirror

This is a staged implementation, NOT a claim that it is installed on the VPS.

Source of truth: independently Ed25519-signed `glacier-browser-updates-v2` manifests. The sync script validates each signature with the existing v2 public key, canonical GitHub tag, version, size, and SHA-256. It downloads both original release assets and stores verified EXE/DMG files in the existing owner VPS download directory. It refuses same-version replacement or rollback.

## One-time VPS setup (Ubuntu, from the existing repository)

```bash
cd /home/ubuntu/comfyui-director-release
HTTPS_PROXY=http://127.0.0.1:1081 git pull --ff-only
sudo apt-get install -y python3-cryptography
sudo test -d /var/lib/glacier-preview-downloads
sudo cp vps-control/glacier-signed-mirror.service /etc/systemd/system/
sudo cp vps-control/glacier-signed-mirror.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now glacier-signed-mirror.timer
sudo systemctl start glacier-signed-mirror.service
sudo journalctl -u glacier-signed-mirror.service -n 40 --no-pager
```

If the service user cannot write into the existing mirror directory, grant ONLY the required write access to that specific directory, not broad filesystem permissions.

The VPS may require outbound GitHub connectivity or an explicitly configured service proxy. The interactive `HTTPS_PROXY` for git does not automatically configure the systemd service. Set a drop-in with `Environment=HTTPS_PROXY=...` and `Environment=HTTP_PROXY=...` if needed; verify service-side DNS and connectivity before relying on the timer.

## Verification

```bash
python3 -m json.tool /var/lib/glacier-preview-downloads/windows-x64.json >/dev/null
python3 -m json.tool /var/lib/glacier-preview-downloads/macos-arm64.json >/dev/null
ls -lh /var/lib/glacier-preview-downloads/GlacierBrowser-v0.20.8-*
curl -fIs https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.8-Windows-Setup-x64.exe
curl -fIs https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.8-macOS-AppleSilicon.dmg
```

The current v0.20.8 manifests are cryptographically bound to GitHub installer URLs. **Do not edit the signed URL field**: changing it breaks the signature and installed clients refuse it. This step guarantees VPS-side storage/distribution only, not in-app direct-from-VPS installation. A future canonical release must have VPS-origin URLs signed into the manifests, update both client allowlists, and verify the VPS installer hash before prompting installation. Keep legacy client update paths intact until that migration is proven.
