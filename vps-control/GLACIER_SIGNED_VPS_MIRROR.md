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

## Permanent independent Windows releases (no action per version)

The existing OIDC notification receiver and 30-minute mirror timer remain
installed. New Windows versions do not depend on macOS releases and do not
require per-version VPS commands or manual signed-JSON modifications.

1. GitHub builds and publishes the next canonical Windows Release.
2. The existing GitHub OIDC notification queues the installed VPS mirror
   service. That worker dynamically discovers the newest Windows Release,
   verifies exact GitHub Release SHA-256/size and atomically stages the EXE
   in the existing owner VPS download directory.
3. A GitHub Windows-only signing workflow independently downloads and hashes
   the entire owner-VPS EXE. It updates the existing pinned Ed25519 v2
   windows-x64.json ONLY after matching the canonical immutable digest.
   The macos-arm64.json channel is preserved and may lag Windows.
4. A second verified OIDC notification queues the VPS mirror, which verifies
   the new signed channel and exact local EXE digest before atomic publishing.
5. Installed Windows clients fetch only the signed VPS HTTPS URL; they verify
   the signed manifest and complete file SHA-256, then request user consent
   for Setup execution.
6. The existing VPS timer and GitHub Windows signing schedule retry transient
   failures without operator involvement.

One-time code migration (NOT repeated on each release)
-------------------------------------------------------

The existing VPS is still running its older paired-only Python mirror. Once
this new dynamic worker is installed into its current checkout, all future
Windows version numbers are discovered automatically without changes to the
service unit or new upload scripts. Existing systemd timer and OIDC receiver
are reused.

    cd /home/ubuntu/comfyui-director-release
    HTTPS_PROXY=http://127.0.0.1:1081 HTTP_PROXY=http://127.0.0.1:1081 git pull --ff-only
    bash vps-control/enable-glacier-automatic-releases.sh

The one-time installer does not edit service units, sudoers, Nginx, GPU, Mac
or signing keys. It checks the installed services, retains the mirror's
NoNewPrivileges=true sandbox, runs mirror tests, stages the latest canonical
Windows EXE, validates its exact published SHA-256/size and HTTPS endpoint,
and checks both existing Ed25519-signed manifests.

Automated GitHub Actions:
- glacier-windows-signed-auto.yml (every Windows Release + retries)
- glacier-preview-immediate.yml (authenticated OIDC receiver)
- glacier-browser-signed-updates.yml (paired compatibility releases)

Until this one-time VPS code migration is applied, latest standalone Windows
installer URLs may return 404 and signed feed publication remains blocked.
Never bypass the full VPS hash gate or hand-edit either signed JSON.

## Verification

```bash
python3 -m json.tool /var/lib/glacier-preview-downloads/windows-x64.json >/dev/null
python3 -m json.tool /var/lib/glacier-preview-downloads/macos-arm64.json >/dev/null
ls -lh /var/lib/glacier-preview-downloads/GlacierBrowser-v0.20.8-*
curl -fIs https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.8-Windows-Setup-x64.exe
curl -fIs https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.8-macOS-AppleSilicon.dmg
```

The current v0.20.8 manifests are cryptographically bound to GitHub installer URLs. **Do not edit the signed URL field**: changing it breaks the signature and installed clients refuse it. This step guarantees VPS-side storage/distribution only, not in-app direct-from-VPS installation. A future canonical release must have VPS-origin URLs signed into the manifests, update both client allowlists, and verify the VPS installer hash before prompting installation. Keep legacy client update paths intact until that migration is proven.

## v0.20.10 signed VPS migration: staging before signing

The owner VPS successfully hosted v0.20.8/0.20.9 previously. No new Nginx
routes, domain, tunnel, secret, or GPU deployment is required.

**Reason for the temporary v0.20.10 404:** the original mirror downloaded
only the version in the existing signed feed (v0.20.9). The signer correctly
refused to publish v0.20.10 until both installers existed on VPS, so neither
side advanced. The mirror now breaks this dependency by staging the newest
canonical paired GitHub Releases with independent GitHub asset digests; it
does NOT alter an existing signed manifest during staging.

Existing VPS operator (regular sudo-enabled user), one-time upgrade:

```bash
cd /home/ubuntu/comfyui-director-release
HTTPS_PROXY=http://127.0.0.1:1081 HTTP_PROXY=http://127.0.0.1:1081 git pull --ff-only
bash vps-control/upgrade-glacier-signed-mirror.sh
```

That script is idempotent and checks for an existing timer and clean branch,
runs tests, installs only the two existing systemd mirror unit files, stages
both installers, compares immutable SHA-256 values, and probes the existing
HTTPS download routes. It does not touch nginx, legacy preview routes, mobile
services, GPU power, account data or existing signing keys.

After staging, the next scheduled
`.github/workflows/glacier-browser-signed-updates.yml` run reads BOTH VPS
installer bytes and independently checks SHA-256 against canonical GitHub
Release digests. Only after both match will it set
`GLACIER_VPS_MIGRATION_READY=1` for the signing step. Then the existing VPS
mirror timer publishes the signed v0.20.10 JSON files, leaving older signed
versions cryptographically immutable.

**Do not hand-edit signed JSON or force publication against a 404.** Running
GitHub Actions by itself does not deploy a new Python script onto the VPS.
