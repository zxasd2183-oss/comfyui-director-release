# Director UE Worker V0.5.1 — non-destructive exposure correction

## What has already been proven

- V0.4 produced four real 720×1280 PNG files from UE 5.8 MRQ.
- The original V0.3 stage has overbright point lights
  `V03_Key_Light=18000` and `V03_Fill_Light=9000`.
- Shot 13 also has a camera distance/composition issue. Exposure repair does
  not claim to solve that.

## This patch

1. **Do not edit** `Content/Director/V03/Maps/WaitingOffice_EP01_Stage.umap`,
   any of the 31 original shot sequences, or the V0.2 assets.
2. Each V0.5.1 preview job makes a **private per-job stage map** via UE 5.8
   `LevelEditorSubsystem.new_level_from_template(new_path, V03_SOURCE_STAGE)`
   under `/Game/Director/V051/Maps/WO_EP01_ExposurePreview_<job_id>`.
3. In the NEW map only, find exactly one `V03_Key_Light` and one
   `V03_Fill_Light` and check expected original intensities before changing
   to `800` / `400`. If the source differs, fail without guessing.
4. Save only the new map, then MRQ renders against its exact fixed path with
   the existing 31 camera sequences, selecting the same four shots
   01/13/26/31.
5. SHA-256 the source `V03.umap` before creation and again before and after
   actual rendering. Any unexpected source mutation fails the receipt.
6. The per-job receipt records the cloned preview map, source map digest,
   light intensities and the original four PNGs + ZIP checksum.
7. Remove the artificial `2 attempts per rolling 24h` hard cap. Still
   enforce only one active job, fixed allowed scripts and shot IDs,
   per-process timeouts and no automatic retry.

**No official Epic setting is claimed to guarantee a perfect exposure.**
`800/400` is the first controlled lighting hypothesis, not a calibrated
reference target. Re-examine actual pixels after this run and adjust lighting
using logged, operator-initiated repeats if necessary. Do not report success
solely because Unreal returns exit 0.

## Rollout

1. Review this branch against the deployed V0.5.
2. Confirm no UE job is active and keep copies of original persistent assets.
3. Use the guarded Windows installer `ue-worker/install-v051.ps1`; it keeps
   the original Worker task name and token/SSH tunnel, backs up scripts,
   refuses to touch UE commandlets still running, and rolls back on failed
   Worker health.
4. Check `get_ue_worker_status` reports `worker_version=0.5.1`.
   The existing VPS Hub API needs no changes; V0.5 job submit/log/cancel
   tools continue working.
5. Manually submit exactly one `enqueue_ue_previs_stills("WaitingOffice",
   "EP01")` job from the approved Director Studio shot plan.
6. Inspect the resulting four PNGs. Check SH13 camera distance separately.
   Confirm `source_stage_unchanged=true` and the source map SHA against the
   original source asset.
7. Use `get_ue_job_logs` to investigate any failed UE runs and rerender as
   needed; the artificial daily quota is gone.
8. Preserve the original V0.4 PNG ZIP, V0.3 level/31 sequences and V0.2
   original assets.

### Limitations

The live Windows UE 5.8 implementation must confirm that
`new_level_from_template` preserves per-camera bindings in the copied level.
Offline fake-engine CI verifies the expected API calls and fail-closed output
contract, but it cannot guarantee real render quality. Do not declare the
visual issue fixed until an operator inspects newly rendered pixels.
