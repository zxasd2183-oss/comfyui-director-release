# Director UE Worker V0.6 — signed unattended upgrades

**Status:** implementation in PR; NOT yet installed or running on Windows.
The production Worker continues to report V0.4.0 until the Windows/VPS
operator deploys a subsequent release. This PR does not claim that GPU
rendering/exposure is fixed.

## Design

1. Keep the existing **non-admin** `DirectorUEWorker` task,
   `C:\ProgramData\DirectorUEWorker` code/data and SSH reverse tunnel.
2. A **separate elevated, pull-only scheduled task**
   `Director-UE-Signed-Updater` is installed **once** locally by an admin.
   The privileged updater lives in SYSTEM/admin-only
   `C:\ProgramData\DirectorUEUpdater`. It listens on NO port.
3. Every five minutes, the updater reads the fixed
   `ue-worker-updates/channel.json` on GitHub. The first channel is
   intentionally absent until a correctly signed release is published.
4. The channel JSON is a strict Ed25519-signed manifest. The updater
   verifies its signature with a single **administrator-pinned 32-byte
   public key**, enforces monotonically increasing versions and requires
   a fixed-size SHA-256-pinned archive from the matching GitHub release.
5. The ZIP is restricted to an exact set of eight Worker .py files,
   rejects path traversal/symlinks/extra entries, syntax-checks each,
   and verifies `agent.py` declares the signed version.
6. If a UE commandlet is active, **do not upgrade**. Otherwise, make an
   admin-only backup, persist a rollback journal, stop only
   `Director-UE-Worker-V02`, replace the eight reviewed scripts,
   restart only that task and verify its real version over loopback.
7. If the new Worker fails health validation, automatically restore the
   last healthy files and restart the Worker. A crash mid-update leaves
   the journal for recovery on the next scheduled run.

No arbitrary PowerShell, caller-selectable URL, package filename, PID,
filesystem path or executable may be supplied through ChatGPT/MCP.
Private signing keys NEVER reside on the Windows worker or in the
repository. No GPU rendering is started by this updater.

## One-time trust/bootstrap (must be completed by the operating administrator)

### 1. Install V0.5 first

Read `V05_REMOTE_OPERATIONS.md`. Deploy `install-v05.ps1` to the Windows
node and update `vps-control/hub_app.py` and `ue_worker_rpc.py` on VPS.
Verify live Worker `0.5.0`, existing fixed SSH forwarding, and the
`get_ue_job_logs` and `cancel_ue_job` tools. No project rebuild.

### 2. Provision a dedicated release signing key, ONCE

On a **trusted operator machine**, use `cryptography` to create an
Ed25519 keypair. Put the 32-byte raw private key hex only in GitHub Actions
secret `DIRECTOR_UE_SIGNING_PRIVATE_HEX`. Put its matching 32-byte raw
public key hex into repository variable
`DIRECTOR_UE_SIGNING_PUBLIC_HEX`. Keep an offline secure backup of the
private key; do not paste it into chat, logs, PRs, or terminal output.
Do **not** reuse the Glacier/Jipite signing keys.

The *exact same public key hex* is the argument to the Windows installer:

```powershell
# Run in an elevated PowerShell console from the reviewed checkout.
.\ue-worker\install-signed-updater.ps1 -PinnedPublicKeyHex '<PUBLIC_KEY_HEX>'
```

This uses the original `DirectorUEWorker` bearer token for a
**loopback health check only**; it does not rotate, publish, or print it.
It requires that the existing V0.5 Worker is healthy. It does NOT launch
untrusted code or change Windows user accounts. The SYSTEM updater code
folder is protected by an admin-only ACL.

Ensure the Python interpreter scheduled under SYSTEM can import
`cryptography`, and confirm `Director-UE-Signed-Updater` runs without
error. The signed-channel branch exists but has no signed manifest yet.
Network access to the fixed GitHub raw and release hosts is required.

### 3. Review and merge V0.6, then sign the first release

The workflow `.github/workflows/ue-worker-signed-release.yml` runs
*only from main* via a manual GitHub Actions `workflow_dispatch`
with `version=0.6.0`. It refuses to sign if the code's declared Worker
version differs or if the two signing keys mismatch. The step executes
only the **trusted main-branch signer**, not a downloaded payload.
It creates the immutable GitHub release ZIP, then advances the signed
`ue-worker-updates/channel.json` only after all checks pass. Never
overwrite release tags or old signed channels.

A Windows updater that trusts the pinned public key will then
automatically detect and apply 0.6.0 on its next check, provided no UE
commandlet is active. Confirm that the real Worker reports 0.6.0 and
that `get_ue_job_logs` and `cancel_ue_job` still work.

## Debug mode change in V0.6

The V0.4 **two preview attempts per rolling 24h** hard limit is
**removed** from `ue_jobs.py` in V0.6. Old quota state files remain
untouched but ignored; Windows Worker upgrades do not modify them.
Safety checks that remain: one active UE job at a time, fixed allowlisted
scripts/shot plan, strict subprocess timeouts, and no automatic render
retry. Legitimate repeated manual UE/MRQ tests are permitted.

## Out of scope

- Signed updater does not deploy VPS Hub code. The privileged VPS
  updater must be configured separately; do not claim full automated
  dual-host upgrades until that exists.
- No GHA secret can be provisioned through the current ChatGPT
  GitHub connector; the trusted operator must configure it once.
- Signature verification does not guarantee visual correctness.
  V0.4's four PNGs were real but overexposed; the rendering pipeline
  still needs a non-destructive exposure fix and another visual check.
