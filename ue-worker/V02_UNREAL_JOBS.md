# Director UE Worker V0.2 — Studio episode → Unreal Sequencer

V0.2 **adds a real Unreal Editor commandlet job**, without changing the
working Windows ↔ VPS SSH tunnel or removing any V0.1 API.

## Source of truth

`enqueue_ue_episode_timeline(project_id, episode_id)` is an MCP tool added
to Director Hub. It fetches the **registered shots** from Studio's existing
`get_production_episode` read API, verifies the snapshot is complete, orders
shots by ordinal and sends only IDs, durations and 24 FPS to the Windows worker.

For `WaitingOffice / EP01` the expected result is 31 timed sections,
160,000 ms, 3,840 frames. This is a timing-only episode; the historical
2D/H3-oriented narrative and image candidates remain unchanged in Studio.
They are reference material, **not yet imported MetaHumans**.

## New tools

- `enqueue_ue_episode_timeline(project_id, episode_id)`: start UE Editor on the
  metered Windows machine; returns an accepted job ID, not a rendering result.
- `get_ue_episode_job_status(job_id)`: fetch queued/running/succeeded/failed,
  with a bounded asset path on success.

The Windows worker accepts only fixed job type `build_episode_timeline`, and
only a validated shot plan. It rejects command lines, script paths, arbitrary
project paths and unknown parameters. The old `prepare_workspace`, status
and capabilities APIs remain available. No arbitrary remote shell/Python.

## Actual Unreal implementation

1. Create `C:\DirectorVirtualStudio\DirectorVirtualStudio.uproject` only
   if it is absent (or matches our managed manifest byte-for-byte).
2. Enable PythonScriptPlugin + EditorScriptingUtilities.
3. Run *bundled and reviewed* `unreal_build_episode.py` through the
   UE 5.8 `UnrealEditor-Cmd.exe -run=pythonscript -script=...` interface.
4. Create 31 shot LevelSequence assets at `/Game/Director/Shots`.
5. Create an episode master at `/Game/Director/Episodes` with
   `MovieSceneCinematicShotTrack` containing consecutive subsections.
6. Save assets and return an explicit result manifest.
7. A commandlet exit failure, missing result or mismatched frame count
   marks the job failed. Logs remain local to the job's `Jobs/<id>` folder.

**No camera actors, character animation, MetaHuman bodies/heads, audio,
rendered frames or MP4 are produced in V0.2.** These require later
approved assets and a Movie Render Pipeline job.

## Important security boundary: no Unreal Editor as LocalSystem

V0.1's Worker Scheduled Task ran as SYSTEM, fine for V0.1 status probes.
Unreal Editor may execute plugins and project startup scripts, so V0.2's
commandlet refuses to run as SYSTEM or Administrator.

The new `install-v02.ps1` bootstraps a dedicated, non-admin Windows local
account and an auto-start Scheduled Task:
`Director-UE-Worker-V02`. Its random credential stays on the Windows host,
not in source code or chat. The worker code and token remain admin-owned;
only its data workspace is writable by this account. Original V0.1 task is
disabled only after the new V0.2 endpoint passes a status probe.

A Windows Server GPU host may restrict Scheduled Task batch logons or a
Python installation to the Administrator profile. Resolve these locally,
without changing the VPS, and **do not weaken the account or port boundary**.
The installer must report success only if its V0.2 task actually starts.

## Deployment

- Do not merge this branch directly into production without review.
- Obtain a clean checkout of `feature/ue-worker-v02-unreal-jobs`.
- On Windows GPU, from an **elevated local PowerShell**, run
  `ue-worker/install-v02.ps1` from its source directory.
- Confirm the existing `ue_worker_tunnel` remains up and that Windows
  `127.0.0.1:19010/v1/status` returns version `0.2.0` when authorized.
- On VPS, use the guarded `vps-control/install-ue-hub-extension.sh`.
  It backs up the old Hub files, checks the tunnel, deploys the expanded
  Hub code and restarts only the existing Hub MCP service.
- Keep existing Studio, Hub tokens, power core, mobile approver, nginx, and
  the SSH setup unchanged. Do not copy secrets into GitHub.
- Ensure the ChatGPT Director Hub connector re-discovers its two new tools.

## Real-machine acceptance

1. V0.1 status and workspace tools are still available.
2. V0.2 reports `ue-worker-01`, fixed `build_episode_timeline` capability.
3. The new scheduled task runs as the **unprivileged** user, not SYSTEM.
4. The VPS sends the actual Studio shot list, never an arbitrary payload.
5. A job receives ID, queued/running state and *observed* terminal result.
6. One `WaitingOffice/EP01` job produces master sequence and 31 shot
   LevelSequence assets with a final playback end frame of 3840.
7. No stdout or error text can disclose the 64-hex-character worker token.
8. Any UE failure is visible as a failed job, not a false success.

## Documentation provenance

Epic UE 5.8 official docs: Python editor commandlets, Sequencer Python
asset creation, LevelSequence display/playback frame APIs, and
MovieSceneCinematicShotTrack.

Next iteration: bind digital actors and cameras to these timed sections,
then expose a bounded MRQ render job.

## Verified on the real UE 5.8 machine (2026-11-10)

An operator deployed V0.2 on Windows Server 2022 with RTX 4090.
Successful job: `34b83082af3f46dcbdd21e1c3c759e2b`.

- Unreal `/Game/Director/Episodes/WaitingOffice_EP01_Master`:
  31 cinematic shot sections, 160 seconds at 24 FPS, playback [0,3840).
- Confirmed `LevelSequence.add_track` works in actual UE 5.8.
  The removed `add_master_track` failed the first deployment; source and
  the fake UE test now use only `add_track`.
- The dedicated `DirectorUEWorker` account needed `SeBatchLogonRight`
  before Task Scheduler could start it.
- The V0.1 worker can leave a stale listener after stopping the task. The
  installer now checks TCP 19010's process **owner SID and exact expected
  agent.py command line** before stopping it, and refuses unknown listeners.
- Subsequent V0.2 installs reuse the existing scheduled-task credential
  instead of resetting the non-admin account's password.

**CI tests and Windows script syntax pass; the new installer changes have
not yet been retested on the live machine.** Existing deployed V0.2 works
with the initial operator-side corrections. Preserve existing episode assets:
the current commandlet refuses overwriting an existing master sequence, so
do **not** re-enqueue EP01 just to check service availability.

Recommended order: review and deploy the committed installer fixes at a safe
idle point, verify V0.2 endpoint ownership and heartbeat, and then do one
planned Windows reboot to check auto-start and tunnel reconnection. Do not
reboot while an Unreal commandlet is rendering or saving assets.
