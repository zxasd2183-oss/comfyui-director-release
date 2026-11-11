# Director UE Worker V0.3 — Real Stage and Per-Shot Cameras

This builds actual Unreal Editor **level geometry and cinematic camera cuts**,
not a text-only plan. It is intentionally a blocking/previsualization stage,
not a final cast or a rendered episode.

## Facts and scope

- Only `WaitingOffice / EP01`, from the 31 registered Director Studio shots.
- Fixed 24 FPS, exactly 160,000 ms / 3,840 frames.
- Output is **separate** from successful V0.2 assets:
  - Map `/Game/Director/V03/Maps/WaitingOffice_EP01_Stage`
  - Shots `/Game/Director/V03/Shots/WaitingOffice_EP01_SH01_V03` ... `SH31_V03`
  - Master `/Game/Director/V03/Episodes/WaitingOffice_EP01_Master_V03`
- Blocking-grade hall and entrance: floor, walls, table, door frame, screen,
  two lights and five explicitly labelled geometric proxy cast members.
- 31 persistent CineCameraActors (`V03_CAM_SH01` ... `V03_CAM_SH31`)
  and per-shot camera-cut tracks referencing those actors in the stage map.
- Source-of-truth duration/order still comes from Studio, not the client.
- The V0.2 `WaitingOffice_EP01_Master` and previous 31 `*.uasset`
  **are not modified or replaced**.
- A second attempt to create an existing V0.3 map/master is denied to avoid
  overwriting edits. On partial failure, inspect V0.3 assets before retrying.

## What this does *not* do

No MetaHuman imports or bindings, final character models, facial expressions,
lip-sync, animation, dialogue/audio, visual approval, render frames, or MP4.
`render_ready=false` and `metahuman_bound=false` are mandatory result fields.
The cube geometry is clearly named `V03_Proxy_<Character>` in the level.

## New Hub action

`enqueue_ue_stage_cameras(project_id="WaitingOffice", episode_id="EP01")`

It dispatches one allowlisted `build_stage_cameras` job to the private
loopback Windows Worker. It is **not** an arbitrary Python or shell tool.
Poll `get_ue_episode_job_status(job_id)` for the observed outcome.

The Windows Worker version becomes `0.3.0`; V0.1 status and V0.2 timeline
APIs remain intact. The connector has one new Hub tool; the existing job
status tool is reused.

## Deployment and acceptance

1. Review `feature/ue-worker-v03-stage-cameras`, offline tests and the
   changes relative to the deployed `feature/ue-worker-v02-unreal-jobs`.
2. Use `ue-worker/install-v03.ps1` on the dedicated Windows machine during
   an idle period. It retains the trusted bearer token, preserves the proven
   scheduled task `Director-UE-Worker-V02` and checks `worker_version=0.3.0`.
   It does not change the SSH tunnel or create a new public service.
3. On VPS use the existing guarded
   `vps-control/install-ue-hub-extension.sh` from the V0.3 branch;
   it deploys the Hub changes after checking tunnel and token and restarts
   only the Hub MCP service.
4. Confirm Worker capability `build_stage_cameras`, and that the original
   V0.2 job status remains accessible.
5. Call `enqueue_ue_stage_cameras("WaitingOffice","EP01")` once. It runs UE
   on the metered GPU, so **do not repeat automatically** if it reports an
   error. Inspect commandlet log and partial V0.3 assets before retrying.
6. Reopen the stage map and new master inside real UE 5.8, inspect cameras,
   cut-section binding IDs, geometry, 31 per-shot sequences, 3,840 total
   frames, and that original V0.2 assets are unchanged.
7. Verify the worker reports `render_ready=false`,
   `metahuman_bound=false` and `proxy_actor_count=5`.

**Deployment is not yet performed by this branch.** CI uses a fake Unreal
API to validate structure, but cannot prove the live commandlet can create
a level in headless mode or that camera bindings resolve in the real editor.
These must be verified on the Windows GPU and corrected in source if needed.

## Design provenance

Official Epic UE 5.8 APIs for `LevelEditorSubsystem.new_level`,
`save_current_level`, `EditorActorSubsystem.spawn_actor_from_class`,
`MovieSceneSequenceExtensions.add_possessable` and `get_binding_id`,
`MovieSceneCameraCutSection.set_camera_binding_id`, and
`LevelSequence.add_track`.

## After successful V0.3 acceptance

Import and review 5 unique **actual** MetaHuman/skeletal character assets,
replace proxy bindings, add movements and facial performance. Then introduce
Movie Render Queue as another allowlisted task with actual artifact verification
and a cost cap; never treat a camera-only sequence as a completed episode.
