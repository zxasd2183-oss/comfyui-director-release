# UE Worker shutdown safety migration

The selected CompShare GPU is the Windows UE 5.8 / RTX 4090 machine.
The VPS control path previously inspected a retired ComfyUI/H3 queue and
blocked safe shutdown with `comfyui_queue_not_verified`. Do **not** bypass
power safety checks or claim ComfyUI is still part of production.

## New protection

- Windows UE Worker **1.6.0+** offers authenticated read-only
  `GET /v7/power/readiness` over the existing private SSH reverse tunnel.
- Worker checks the active Director job and a bounded, host-wide Windows
  `tasklist.exe` inventory of Unreal Editor, commandlet, shader compiler,
  Unreal Build Tool, and Lightmass processes.
- VPS power core uses only the pinned loopback `127.0.0.1:18910` endpoint,
  a private systemd credential copy of the Worker token, a pinned node ID,
  a fresh timestamp, and a strict consistent safety receipt.
- **No reachable Worker, invalid token, active task, visible Unreal process,
  incomplete process inventory, wrong node, stale/malformed result, or
  redirect ⇒ shutdown DENIED.**
- Start remains controlled by the existing owner-authorized provider path.
  Stop still does its normal *two* safety preflights and uses the existing
  provider-instance ID and durable audit lease/cooldown. Never change the
  selected GPU instance or disable these checks.
- The old `DIRECTOR_GPU_MCP_URL` and ComfyUI queue settings can remain in the
  root environment temporarily but **cannot authorize shutdown**.

## Installation and verification (root VPS maintenance)

The signed Worker and Hub update feeds cover only their pinned Worker/Hub
files. The **power control service, power_ops.py and systemd unit are NOT
automatically installed** by either feed. They require an authenticated
administrator-run VPS maintenance upgrade.

1. Verify the *actual* Windows Worker is 1.6.0+ with
   `get_ue_worker_status` and that it is the selected RTX 4090 machine.
2. Verify the new `get_ue_worker_power_readiness` Hub tool is reachable.
   It may return `safe_to_stop: false` while busy; do not shut down.
3. In a trusted checkout of this reviewed repository, execute the existing
   root-only `vps-control/install-hub-v06.sh` installer on the VPS. The
   updated installer copies the power core and power service unit, adds the
   private `ueworkertoken` systemd credential, backs up and rolls back all
   files on failure, and checks the UE Worker read-only safety route.
4. Confirm `director-power-mcp`, `director-hub-mcp` and
   `director-hub-bridge` are active and use read-only readiness to verify
   that no UE tasks/processes exist.
5. **Do not invoke `stop_gpu_now` during deployment verification.**
   A real stop is a separate owner-requested action, after checking saved
   assets/outputs. Never interpret `Running` or Worker health as proof of
   zero processes.

Safety verification cases (offline CI) include busy Director jobs, independent
Unreal processes, wrong node, stale or spoofed responses, redirect, missing
token, wrong OS, inaccessible process enumeration, and old ComfyUI responses.

For a full end-to-end proof without actually stopping the VM, an operator
must verify the new power core version from its installed root-owned file and
a fresh UE readiness receipt. A Worker/Hub version alone does **not** prove
that the VPS power core has been upgraded.
