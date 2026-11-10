# Director UE Worker V0.1 — Windows GPU → existing VPS → Director Hub

This is a **first functional control plane**, not an Unreal Engine installer.
It reuses the already-established reverse SSH tunnel:

- Windows worker: `127.0.0.1:19010`
- VPS tunnel entry: `127.0.0.1:18910`
- VPS Hub: existing MCP server and private token, unchanged public hostname.

The former H3 GPU is gone; this change does not assume it exists and does not
remove historical H3 tools or production records.

## What has actually been implemented

- Token-authenticated Windows HTTP worker, bound to loopback only.
- `get_ue_worker_status`: GPU (via installed `nvidia-smi`), Windows, Python,
  detected UnrealEditor.exe installations and workspace state.
- `get_ue_worker_capabilities`: reports the exact supported operations.
- `prepare_ue_workspace`: creates **only** predefined production folders
  under a fixed local workspace root.
- Separate VPS pinned adapter, secret file, allowlist, no redirect/proxy/remote URL.
- Offline tests, Windows scheduled-task installer, and guarded VPS Hub installer.

**Not yet built:** installing UE through Epic, controlling Unreal Editor,
creating MetaHumans, loading Studio scenes, rendering, or general job dispatch.
There is intentionally **no remote PowerShell / arbitrary Python command API**.

## Windows installation

Needs elevated PowerShell and Python 3.10+ present. Run from this folder:

```powershell
.\install-worker.ps1
```

This creates `C:\ProgramData\DirectorUEWorker\worker.token`, restricts Windows
ACLs to SYSTEM/Administrators, copies `agent.py`, registers the startup task
`Director-UE-Worker` under SYSTEM, and starts it. It **does not touch SSH**.

Check task status:

```powershell
Get-ScheduledTask -TaskName Director-UE-Worker | Get-ScheduledTaskInfo
```

The worker is not publicly reachable. An unauthenticated request to
`http://127.0.0.1:19010/v1/status` must be rejected with HTTP 401.

## Provision token to existing VPS (one-time secure transfer)

From an authorized Windows terminal, use an existing **verified** SSH
management connection to send the 64-hex-character token to the Ubuntu VPS,
then install it at `/etc/director-ue-worker.token` with owner
`root:directorpower` and mode `0640`. Never paste the token into chat,
a GitHub issue, shell history, or a command line argument.

A trusted operator with local SSH access can use:

```powershell
$token = Join-Path $env:ProgramData "DirectorUEWorker\worker.token"
$adminKey = Join-Path $env:USERPROFILE ".ssh\ue_vps_admin"
scp -i $adminKey $token ubuntu@111.230.226.74:/home/ubuntu/.director-ue-worker.token.pending
ssh -i $adminKey ubuntu@111.230.226.74 "sudo install -o root -g directorpower -m 0640 /home/ubuntu/.director-ue-worker.token.pending /etc/director-ue-worker.token && rm -f /home/ubuntu/.director-ue-worker.token.pending"
```

Use a secured private terminal for this step. Remove temporary files even
after a failed transfer. If sudo is unavailable, stop: do not bypass access controls.

## VPS Hub extension

Ensure this feature branch is available in a **separate checkout**, not by
overwriting a dirty production checkout. From the repository root:

```bash
sudo bash vps-control/install-ue-hub-extension.sh
```

The installer fails closed if the Hub service is already down, if the token
is missing, if the Windows agent is unreachable over the tunnel, or if Python
files fail compilation. It creates a root-only backup, changes only the
Hub application and local adapter, restarts **only** `director-hub-mcp.service`,
and verifies the authenticated Windows status under the Hub service identity.
On failure it attempts to roll back the Hub changes.

It does not alter Nginx, GPU power management, SSH keys or the existing tunnel.

## Acceptance

1. Windows Scheduled Task: running.
2. No Internet-exposed listener on TCP 19010 or 18910.
3. VPS `ss -lnt` shows only `127.0.0.1:18910`.
4. Unauthorized local worker GET returns HTTP 401.
5. Authorized Hub status returns `ok:true`, `node_id:ue-worker-01`.
6. Capabilities contain only `prepare_workspace`.
7. Workspace action creates fixed directories, no external commands.
8. Original Director Studio and Hub endpoints still work.

**Do not claim completion until steps 1–8 are verified on the real machines.**

## Next engineering iteration

Once node health is confirmed, add a bounded, audited job queue for UE-specific
operations: inspect engine version, create a project using pinned templates,
run a fixed Unreal Python commandlet, inspect result artifacts, render
Sequencer and report progress. No arbitrary shell exposure.
