# Glacier: bridge existing authenticated OIDC notification to signed mirror

**Not a new receiver, domain, or GPU action.** The current
`https://sync.borealos.cn/downloads/notify` receiver already validates the
short-lived GitHub OIDC token and triggers the legacy preview sync. Preserve it
for old clients. Add **one** bounded second action after successful OIDC
authorization: queue the already-installed `glacier-signed-mirror.service`.

This repo does not contain the currently running VPS receiver source code, so
installing this helper alone does not modify its HTTP request handler.

## Least-privilege service authorization (existing VPS)

First verify the running receiver's actual system user:

```bash
systemctl show glacier-preview-notify.service -p User --value
```

If and only if it prints `glacierpreview`, install the exact command allowlist:

```bash
cd /home/ubuntu/comfyui-director-release
sudo install -o root -g root -m 0440 \
  vps-control/glacier-signed-mirror-notify.sudoers \
  /etc/sudoers.d/glacier-signed-mirror-notify
sudo visudo -cf /etc/sudoers.d/glacier-signed-mirror-notify
```

If the service user differs, **do not broaden the sudoers policy or use a
wildcard**. Check the receiver's effective identity before authorizing it.

## Connect the existing, OIDC-verified handler

Leave the existing preview-sync call unchanged. **After** OIDC authorization
and claim verification, invoke
`vps-control/glacier_signed_notify_hook.py:queue_signed_mirror()`.
Its command is fixed (no user-controlled arguments):

```text
sudo -n /usr/bin/systemctl start --no-block glacier-signed-mirror.service
```

For a receiver located outside the Git checkout, load the hook from the
trusted repository file by an approved absolute path/import. Do not expose
this action as a new anonymous route, do not accept an arbitrary service
name from the HTTP body, and do not run a shell command with user input.

Return HTTP 202 only after the two configured jobs are successfully queued.
HTTP 202 means **accepted**, not **mirror finished**. Audit a single
non-sensitive event (request accepted, mirror job queued) without saving
the OIDC token. The existing 30-minute mirror timer remains a safety fallback.

If the receiver itself directly executes the old preview script (rather than
a systemd oneshot service), attaching `OnSuccess` to a legacy unit would be
ineffective: modify the authenticated handler at the actual execution point.

## Receiver sandbox compatibility (November 2026 production fix)

**Root cause of misleading HTTP 202:** The live `glacier-preview-notify.service`
receiver already called `queue_signed_mirror()`, but its sandbox had
`NoNewPrivileges=true`. Even with the exact sudoers allowlist, sudo could
not elevate *inside that receiver unit*. A host-level
`sudo -u glacierpreview sudo -n …` check did not reproduce the sandbox.

The live receiver implementation and its full base systemd unit currently
live outside this Git repository (under `/opt/glacier-preview-downloads`
and `/etc/systemd/system`). **Do not replace either with guessed templates.**
Instead, this repository now provides an explicit **receiver-only systemd
drop-in** at
`vps-control/glacier-preview-notify.service.d/10-signed-mirror-sudo.conf`:

```ini
[Service]
NoNewPrivileges=no
```

This makes the exception persistent even if the receiver's *base unit* is
reinstalled with `NoNewPrivileges=true`. It does **not** weaken
`glacier-signed-mirror.service`, which retains `NoNewPrivileges=true`:
the mirror itself does not run sudo. The receiver exception is bounded by
its user `glacierpreview`, the **exact single-command sudoers allowlist**,
OIDC claim verification, and the existing systemd sandbox settings.

After a future receiver redeploy, apply or re-apply the reviewed override
using a normal sudo-enabled VPS login (the installer validates the service
user, compares the installed sudoers with the reviewed policy, saves an
existing drop-in if changed, and restarts **only** the receiver):

```bash
cd /home/ubuntu/comfyui-director-release
git pull --ff-only
bash vps-control/install-glacier-preview-notify-sudo-compat.sh
systemctl show glacier-preview-notify.service -p NoNewPrivileges --value
```

The expected effective setting is `no`. When inspecting the receiver,
run `systemctl cat glacier-preview-notify.service` to confirm the drop-in
is loaded; `systemctl show` is the authoritative effective-setting check.
If sudoers or service identity differs, the installer fails closed rather
than extending privileges.

**Request contract:** After OIDC verification, enqueue both the signed
mirror service and the retained legacy preview task. Respond `202` **only
if both were queued**, otherwise respond `503` for a partial queue. Invalid
OIDC requests must be denied (`401` or `403`, according to the deployed
receiver). A genuine GitHub OIDC event plus follow-up VPS version promotion
is still required for end-to-end acceptance.

## Post-change verification

1. On VPS, `sudo visudo -cf /etc/sudoers.d/glacier-signed-mirror-notify`.
2. Confirm an **unauthenticated** `POST /downloads/notify` is denied (HTTP 401/403).
3. Trigger the existing GitHub workflow
   `.github/workflows/glacier-preview-immediate.yml` once (or wait for the
   signed publisher's successful workflow_run event).
4. Confirm its authenticated POST returns HTTP 202 and the signed unit has
   started; verify `journalctl -u glacier-signed-mirror.service -n 30 --no-pager`.
5. Both public `/downloads/windows-x64.json` and `/downloads/macos-arm64.json`
   must match the current **canonical signed GitHub v2 manifests** (v0.20.15
   was verified in November 2026); both must retain `v2-259ea4a7b9da4bea`
   and verify with the pinned Ed25519 public key.
6. Both installer downloads must still return 200/206, with the same sizes
   and SHA-256 as the signed manifest.

This does not alter or disable the old `*-preview.json` routes.
