# Glacier Browser for macOS — immediate VPS updates using GitHub OIDC

Glacier Mac now uses the same **short-lived GitHub OIDC** principle as the
already-working Jipite APK delivery pipeline, but with separate, tightly
limited permissions. No VPS SSH private key or long-lived webhook token is
needed in GitHub Actions.

## Security boundaries

- Trigger: a commit to the already Ed25519-signed
  `channels/macos-arm64.json` on `glacier-browser-updates`.
- OIDC audience: `glacier-macos-vps-update-sync` (different from Jipite).
- Allowed GitHub identities: only
  `.github/workflows/glacier-macos-vps-immediate.yml` on
  `glacier-browser-updates` with a push/dispatch event, or
  `.github/workflows/glacier-macos-vps-manual-sync.yml` on
  `main` with a manual dispatch event.
- VPS entrypoint: HTTPS `POST /glacier-updates/notify`, not the existing
  Jipite `/app-updates/notify` endpoint.
- Loopback receiver: `127.0.0.1:8897` as the unprivileged
  `glacierupdate` user; never accepts a URL, shell command, APK, or DMG.
- Action: run only the preinstalled
  `/opt/glacier-macos-updates/sync-glacier-macos-updates.py` script,
  which independently validates the offline Ed25519 signature, DMG size
  and SHA256 before atomically exposing the Mac version on HTTPS.
- Client: independently checks the signed manifest and DMG SHA256.
  Unsigned Apple installers still require user confirmation.
- Existing `glacier-macos-update-sync.timer` every 30 minutes stays active
  as a fallback, separate from Jipite's hourly timer.
- GPU control, personal Microsoft login, Android APK signing and Jipite
  OIDC verification are unmodified.

## One-time VPS setup

Review the source before executing it. From the *VPS SSH terminal*, not
from the Mac client:

```bash
git clone --depth 1 --branch glacier-browser-updates \
  https://github.com/zxasd2183-oss/comfyui-director-release.git \
  ~/glacier-macos-oidc-install
sudo bash ~/glacier-macos-oidc-install/vps-control/install-glacier-macos-oidc-immediate.sh
```

If this destination directory exists already, update that checkout or
choose another directory; never use `rm -rf` on a directory you have not
inspected.

The script refuses to enable Nginx unless the existing Glacier mirror is
installed, the fallback timer is active, the mobile API path is intact,
and its loopback receiver passes a local readiness test. It backs up
`/etc/nginx/snippets/jipite-mobile.conf`, adds just one exact-match
include, validates with `nginx -t`, reloads, then checks public routes.
On failed endpoint checks it restores the original snippet.

## Acceptance test

The unauthenticated endpoint must return **401** rather than 200/202:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST -H 'Content-Type: application/json' --data '{}' \
  https://jipite.borealos.cn/glacier-updates/notify
```

The existing update manifest must continue to return 200:

```bash
curl -fsS https://jipite.borealos.cn/glacier-updates/macos-arm64.json
```

Next, in GitHub Actions run the **Manually sync signed Glacier macOS
updates via OIDC** workflow on `main`:

https://github.com/zxasd2183-oss/comfyui-director-release/actions/workflows/glacier-macos-vps-manual-sync.yml

Expected: Ed25519 metadata verification OK, VPS OIDC notify **202**,
eventually exact signed Mac manifest served via HTTPS and DMG available
with correct size. GitHub's **202 means accepted, not completed**; the
workflow polls the actual files to verify successful publication.

If notify returns 404, Nginx route is not installed. If 401/403, check the
dedicated workflow_ref, repo/owner immutable IDs, audience, branch and
clock skew; don't disable token verification. If VPS sync fails, inspect:

```bash
sudo journalctl -u glacier-macos-immediate-notify.service -n 50 --no-pager
sudo journalctl -u glacier-macos-update-sync.service -n 50 --no-pager
sudo systemctl is-active glacier-macos-update-sync.timer
```

No passwords or JWTs should be copied into chat or workflow logs.

## Retiring the legacy SSH trigger (after successful 202 + HTTPS validation)

After the OIDC path has passed a full GitHub-to-VPS test, remove unused
GitHub Actions repository secrets:
`GLACIER_VPS_SSH_PRIVATE_KEY`, `GLACIER_VPS_SSH_HOST`,
`GLACIER_VPS_SSH_KNOWN_HOSTS`, and `GLACIER_VPS_SSH_PORT`.

The previous VPS-only `glaciertrigger` authorized SSH key and narrow
sudoers rule should also be revoked after confirmation; review any
other usage before deleting an account or file. Do not confuse this
legacy **SSH trigger key** with the entirely separate offline Ed25519
**Mac release-signing key**. Never delete or expose the release-signing
key as part of SSH cleanup.

The old manual SSH workflow has been replaced by an OIDC-only one.
No changes to Mac installers or an additional DMG build are needed.
