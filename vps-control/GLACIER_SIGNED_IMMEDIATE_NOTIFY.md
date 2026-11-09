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

## Post-change verification

1. On VPS, `sudo visudo -cf /etc/sudoers.d/glacier-signed-mirror-notify`.
2. Confirm an **unauthenticated** `POST /downloads/notify` is denied with 401.
3. Trigger the existing GitHub workflow
   `.github/workflows/glacier-preview-immediate.yml` once (or wait for the
   signed publisher's successful workflow_run event).
4. Confirm its authenticated POST returns HTTP 202 and the signed unit has
   started; verify `journalctl -u glacier-signed-mirror.service -n 30 --no-pager`.
5. Both public
   `/downloads/windows-x64.json` and
   `/downloads/macos-arm64.json` must report **0.20.10**, have the original
   `v2-259ea4a7b9da4bea` key_id and retain their original Ed25519
   signatures.
6. Both installer downloads must still return 200/206, with the same sizes
   and SHA-256 as the signed manifest.

This does not alter or disable the old `*-preview.json` routes.
