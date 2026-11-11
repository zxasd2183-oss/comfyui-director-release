# UE Worker V0.4: first *visible* Unreal Engine output

## Purpose

V0.3 created a real 31-shot CineCamera stage, but there are not yet any
deliverable images or a complete MP4. Before moving on to MetaHuman, V0.4
renders a **small, explicitly non-final proof** of the real stage and camera
bindings. These are not the final character designs.

## Deliverables (only after live UE success)

Four actual UE 5.8 Movie Render Queue stills:

| Shot | Story moment | Output |
| --- | --- | --- |
| 01 | Opening, hall | PNG, 720x1280 |
| 13 | First entrance | PNG, 720x1280 |
| 26 | Screen/system warning | PNG, 720x1280 |
| 31 | Zero and mystery ending | PNG, 720x1280 |

All are **proxy cubes and a crude room**. No MetaHuman, animation, facial
acting, music, subtitles, or MP4 is claimed.

Outputs on the Windows GPU, after success:

`C:\DirectorVirtualStudio\Outputs\V04\<random-job-id>\Previews\`

The durable job receipt lists four filenames, byte sizes, fixed pixel
dimensions, and SHA-256 digests. The actual PNG files **stay on Windows**;
the current MCP connector can report filenames and hashes but **does not
serve remote images or create a browser preview**. To view, open that folder
on the Windows host or transfer the four PNG files via your existing
authenticated workflow. Do not publish the private Worker auth token.

## Worker's allowlist and cost cap

New fixed job: `render_previs_stills`. New Hub tool:
`enqueue_ue_previs_stills("WaitingOffice","EP01")`.

No caller input except project and episode ID. Requests are derived from
Director Studio's complete 31-shot list and rejected unless it exactly
matches the approved 160s/24fps V0.3 episode. The four screenshot shot IDs,
map path, preset asset, size, frame range, output directory and command line
are pinned by source code.

MRQ setup max 180 seconds and each of 4 one-frame renders max 180 seconds.
The worker runs only one UE job at once and does **not** automatically retry
failed renders. A dedicated on-disk rate limiter allows **at most two V0.4
preview attempts in any rolling 24-hour window**, including failed attempts.
It survives the Worker restart and rejects corrupt budget files (fail-closed).
Timeout or missing/corrupt image fails the whole job with
its structured error code.

## Unreal 5.8 implementation

- The fixed `unreal_create_previs_preset.py` commandlet creates a dedicated
  `MoviePipelinePrimaryConfig` preset with PNG output, Deferred Pass,
  720x1280 resolution, and custom frame interval [0,1).
- `ue_previs.py` invokes UnrealEditor-Cmd.exe on the existing V0.3 stage map
  and each of 4 real V0.3 shot sequences using the official:
  `-game -LevelSequence=<asset> -MoviePipelineConfig=<preset>` command.
- Its output validator checks the PNG header, exact dimensions and file
  size bounds; a mere process exit 0 is **not** considered success.
- V0.2/V0.3 maps, sequences and actor bindings are never edited.
- The very first preview job may need to enable `MovieRenderPipeline` in
  the managed Director .uproject file. Before doing so, it verifies the
  entire existing manifest matches the original Director-managed schema
  and backs it up in the private job folder; unfamiliar project files are
  **rejected without modification**. `ensure_project` accepts both managed
  schema variants thereafter.
- UE 5.8 may have an MRQ API or rendering-profile difference that
  automated fake-engine unit tests cannot detect. Live acceptance is
  required. If rendering fails, inspect the `preset.log` or
  `render_01.log` etc. and fix source in the branch before retrying.
- Do not execute if another render job or UE commandlet is active.

## Deployment sequence

1. Confirm V0.3 current state, 1 map + 31 camera cuts + 1 master, and confirm
   that its assets are on persistent storage. Do not rebuild V0.3.
2. Review `feature/ue-worker-v04-previs-stills` (stacked on V0.3).
3. On the existing Windows GPU, use the guarded
   `ue-worker/install-v04.ps1` upgrade with its companion files.
   The current V0.3 worker schedule name, secret, SSH port and VPS stay
   unchanged.
4. Deploy the corresponding Hub update with the repository's existing
   guarded VPS script.
5. Check Worker version `0.4.0` and capability `render_previs_stills`.
6. Start the new job once via `enqueue_ue_previs_stills` and poll
   `get_ue_episode_job_status`.
7. Inspect all four real PNGs visually, including camera angle and the
   legibility of stage structure; inspect every SHA-256 and PNG dimension.
8. Report exact file paths and verified visual findings. Do not claim an
   MP4 or final character/MetaHuman model exists.
9. Only then proceed to MetaHuman imports and actor-performance pipeline.

## Epic documentation

- UE 5.8: *Using Command Line Rendering with MRQ* documents the
  `-LevelSequence` + `-MoviePipelineConfig` route.
- `MoviePipelinePrimaryConfigFactory`, `MoviePipelineOutputSetting`,
  `MoviePipelineImageSequenceOutput_PNG` and
  `MoviePipelineDeferredPassBase` appear in the Unreal Python/API
  documentation.

This is a milestone to show **real pixels**. The actual goal remains
`待回答事务所_EP01.mp4` with final cast, voices, performances, and edit.
