# Director UE Worker V0.5 — controlled remote operations

## Scope

**This is a safe MCP/SSH operations layer, not an unrestricted remote shell.**
The existing private reverse-SSH tunnel `VPS 127.0.0.1:18910 -> Windows
127.0.0.1:19010`, token, dedicated non-administrator Windows account and
persistent V0.2–V0.4 Unreal assets remain unchanged.

New ChatGPT-facing Hub tools:

- `get_ue_job_logs(job_id, kind)` returns the sanitized final 6,000 bytes of
  one fixed logfile. Valid kinds are `unreal`, `preset`, `render_01`,
  `render_13`, `render_26`, `render_31`. No pathname accepted. The
  authenticated Worker verifies that the job exists and denies symlinks.
- `cancel_ue_job(job_id)` requests cancellation of a single active job.
  The process controller only owns subprocess handles created for that job;
  it terminates the exact Windows UE child process tree and marks the job
  `cancelled`. Cannot send arbitrary PIDs or commands. Poll status after the
  cancellation response.
- Already-existing `enqueue_ue_previs_stills(project_id, episode_id)`
  and `get_ue_episode_job_status(job_id)` remain supported. Studio supplies
  the frozen EP01 shot plan.
- `get_ue_worker_status()`, `get_ue_worker_capabilities()` remain available.

Worker job control is authenticated with the existing bearer secret over
private SSH, with strict job ID regexes on both ends, bounded results, no
redirect, no public URL, no arbitrary shell execution, and an unprivileged
Windows executor. Cancelling a job can forfeit in-progress GPU work.
A successful HTTP cancellation response is only an **acknowledgment**, not
proof the process already exited: poll status for `state=cancelled`.

## Deployment requirements (one-time privilege boundary)

1. Merge/review this feature branch **after** V0.4 has been deployed.
2. Confirm no active UE job before upgrading (the guarded installer refuses
   to deploy while an UnrealEditor-Cmd process is executing).
3. A Windows **administrator** runs the reviewed
   `ue-worker/install-v05.ps1` using the complete checkout. The script
   uses the existing local task `Director-UE-Worker-V02`, preserves the
   Worker token, independently running SSH tunnel and existing UE assets,
   and rolls back on failed health.
4. Deploy the updated `vps-control/hub_app.py` and
   `vps-control/ue_worker_rpc.py` through the existing privileged VPS
   deployment mechanism. Restart only the Hub service, not unrelated
   ComfyUI/Glacier/Jipite services.
5. Verify Worker `0.5.0`, the two new tool names and the legacy V0.4
   routes. A ChatGPT MCP connection may need to rediscover tools.
6. Read existing overexposure logs:
   `get_ue_job_logs("2d49a5f2ddfb4abbb45dc3d408901322", "preset")` and
   `get_ue_job_logs("2d49a5f2ddfb4abbb45dc3d408901322", "render_13")`.
   Log access requires the persisted job receipt to still be available.
7. Only then choose a non-destructive lighting/exposure fix and rerender;
   never claim an unchanged overexposed preview is an accepted deliverable.

## About remote deployment of future versions

The Worker is deliberately non-admin and its code directory is read-only
to that account. Therefore it **cannot securely replace its own code**,
and adding a remotely callable PowerShell endpoint would defeat the
privilege boundary. This PR does **not** claim to enable unattended
self-updates.

To make the assistant handle future code deployments, we need a separately
bootstrapped **privileged release agent** that accepts only preapproved,
cryptographically signed packages with pinned hashes and verified release
identities, with an atomic rollback. That is a distinct implementation
milestone; do not fake it by passing arbitrary script paths or elevated
commands through the existing Worker.

## GPU cost protection

The V0.4 preview two-attempts-per-24-hours hard limit is **unchanged in this
branch**, pending a separate explicit decision to remove it for live
debugging. No render is triggered by installing V0.5. Logging is read-only;
cancel may terminate an active render but cannot start a new one.

## Verification

CI runs offline Windows Worker API tests, real child-process cancellation
on Linux without UE, bridge validation, and Windows PowerShell parser
tests. It does **not** claim a live Windows GPU upgrade has happened until
the version and MCP tools are independently observed in production.
