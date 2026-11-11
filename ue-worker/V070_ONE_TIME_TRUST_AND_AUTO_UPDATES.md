# Director UE V0.7.0: one-time trust, then signed Worker + Hub releases

## Why this branch

The live Windows Worker is **0.5.1**, and the last real four-frame UE 5.8
preview run **already succeeded**:

- Job `a7fcd4fe34e849248b7664bc717aa67b`
- 4 real 720×1280 frames, 96 seconds
- Original V03 stage SHA unchanged:
  `7fac6dd780409aef1db577504e145d390fa62f6c39fd160c6d7c122f7ff2f488`

Before this integration, V0.6 auto-update and V0.5.2 preview-reading lived in
different draft branches; deploying one would have overwritten the other.
**This branch includes both** in one version V0.7.0.

## What runs automatically after ONE trusted bootstrap

1. Windows has a **SYSTEM-only signed release poller**. It runs every five
   minutes and can only replace nine exact `DirectorUEWorker` Python scripts
   from `ue-worker-updates/channel.json`.
2. The VPS has a **root-only signed release poller**. It runs every five
   minutes and can only replace `hub_app.py` and `ue_worker_rpc.py` from
   `ue-hub-updates/channel.json`.
3. Both use one dedicated Ed25519 UE production signing key, with **separate
   manifest formats and release tags**. The private key is a GitHub Actions
   secret and a local DPAPI-encrypted backup, *not* in GitHub source,
   Windows Worker, VPS or chat. Both machines pin the matching public key.
4. GitHub publishes unsigned-source-derived **immutable signed archives**
   only from reviewed `main` code after required offline CI, never from a
   PR branch. Channels move forward only after asset publication.
5. Only the Windows updater can change Worker files. Only the VPS updater can
   change the two Hub UE API files. Neither one exposes arbitrary shell,
   URL, public render download, plugin admin session, or GPU power access.
6. Safety gates: validated signature and archive SHA-256, exact file
   allowlists, anti-rollback, no active/queued UE job, fixed system service
   names, code backup, health check, rollback on failure, audited receipts.
   Existing SSH reverse tunnel, token, V03 and V02 assets, output PNGs,
   and independent Glacier/Jipite services are untouched.

## One-time operating steps (not yet performed)

Run from an **elevated Windows PowerShell** in this complete reviewed
integration checkout. Git, Python 3.10+ with `cryptography`, and a GitHub
CLI authenticated account with Actions secrets/variables permission are
required.

```powershell
# Windows only (does not configure the VPS):
.\ue-worker\setup-signed-auto-updates-once.ps1

# Or, if the existing VPS SSH endpoint/account is available, bootstrap BOTH:
.\ue-worker\setup-signed-auto-updates-once.ps1 -VpsSshTarget "root@YOUR_VPS_HOST"
```

What the script actually does:
- Verify Worker is healthy and idle at V0.5.1 / V0.5.2, and the dedicated
  Windows task remains non-admin.
- If 0.5.1, fetch the **fixed SHA** of the previously CI-tested V0.5.2
  checkout, refuse any mismatch, run its guarded installer, require
  V0.5.2 health. This ensures all **nine** signed-release script files
  already exist before any future automated upgrade.
- Provision a new dedicated release signing key with `gh` only when the
  repository public variable is absent. Never overwrite/rekey an existing
  Ed25519 trust root. Use GitHub secret
  `DIRECTOR_UE_SIGNING_PRIVATE_HEX` and public variable
  `DIRECTOR_UE_SIGNING_PUBLIC_HEX`; keep local DPAPI backup privately.
- Install Windows `Director-UE-Signed-Updater` task, verify an actual
  SYSTEM-run health receipt (not just task registration), schedule 5-minute
  polling, preserve previous Worker task and tunnel.
- If `VpsSshTarget` was supplied, send only two fixed root bootstrap
  files via the existing SSH trust, install a 5-minute systemd timer and
  root-protected public key. No existing Hub services are restarted yet.
- VPS requires `cryptography` in the existing
  `/opt/comfyui-director-control/.venv/bin/python`. If missing, installer
  refuses instead of silently installing dependencies into production.
  If VPS SSH target wasn't given, run the reviewed
  `vps-control/install-ue-hub-signed-updater.sh` once on VPS with the
  **public key only**.

**Important:** This bootstrap needs local Windows administrator access and
optionally VPS root. A ChatGPT plugin's "full access" permission cannot
grant those machine privileges. Do not paste the signing private key to chat.

## If Windows updater is ALREADY installed

Do **not** rerun `setup-signed-auto-updates-once.ps1`; it is intentionally
non-idempotent and refuses to replace an installed SYSTEM updater. On the
RTX 4090 host the existing Windows signed updater has already been verified
with a `no_signed_channel` receipt and a working V0.5.2 Worker.

Configure **only** VPS through the separate reviewed script, from an elevated
PowerShell console in the current integration checkout:

```powershell
.\ue-worker\bootstrap-vps-updater-only.ps1 -VpsSshTarget "YOUR_SSH_USER@YOUR_VPS_SSH_HOST"
```

The script reads the existing local pinned **PUBLIC** key, copies only two
reviewed bootstrap files over the pre-existing SSH trust, uses sudo for the
one-time root installation, verifies the timer, and does **not** regenerate
or rotate a signing identity, request GitHub OAuth, touch Windows tasks, or
render new PNGs. The VPS Python environment must already import cryptography.

**PowerShell 5.1 corrections committed to source:** GitHub CLI stderr no
longer becomes a terminating PowerShell error; paths with spaces are passed
as separate argv elements; key generation is executed from a temporary
`.py` script rather than multi-line `-c`; the Windows task is registered
with the Task Scheduler PowerShell cmdlets (proper quoted executable/script
paths and bounded ten-year repeat period). GitHub Actions now checks these
with Windows PowerShell **5.1** as well as `pwsh`.

If the VPS has no known SSH user/host, use its already authorized operator
console to execute `vps-control/install-ue-hub-signed-updater.sh` after
transferring the script and updater module, with only the matching
**public key** argument; do not send passwords, PATs or private keys to chat.

## First signed V0.7.0 release

After the one-time trust step, merge the reviewed entire dependency chain to
`main` (not just this top draft PR), respecting the project's existing
Glacier/Studio changes. A successful trusted-main CI triggers:

- `Publish signed Director UE Worker release` (9 files,
  `ue-worker-v0.7.0`)
- `Publish signed Director UE Hub API release` (2 files,
  `ue-hub-v0.7.0`)

Windows updates first (from 0.5.2 to 0.7.0), then the VPS updater can verify
Worker `active_job_id == null` and update Hub to 0.7.0. Both rollbacks are
local and do not touch UE assets. If one updater is temporarily offline it
will retry on its next timer run; no fixed total completion time is promised.

## What ChatGPT can do after verification

- `get_ue_worker_status`: real version, GPU, active job and signed updater receipt
- `request_ue_signed_update`: request a safe check at NEXT timer poll (not an arbitrary install)
- `get_ue_signed_update_status`: pending request and last signed update receipt
- `get_ue_hub_signed_update_status`: VPS Hub version/verified signed update result
- `get_ue_preview_image(job_id,shot_id)`: return the original, SHA-pinned
  `01`, `13`, `26`, `31` PNG as MCP native image. No new GPU render.
- Existing job submission, logs, status and cancellation remain available.

**Actual visual inspection remains necessary.** The CI image tests use
synthetic PNGs; only the old four real files on Windows can establish whether
lighting and SH13 framing are acceptable. No claim of a finished film or
MetaHuman acting is made.

## Status

**Code + CI only until trusted one-time bootstrap and approved main releases
are complete.** The installed Worker last reported 0.5.1. The VPS
control-center connector was unavailable on the last check. This branch
does not pretend to have administrative remote access or claim deployment.

See also `ue-worker/V052_PREVIEW_IMAGE_ACCESS.md` and
`ue-worker/V06_SIGNED_UPDATER.md` on their respective development branches
for historical design.
