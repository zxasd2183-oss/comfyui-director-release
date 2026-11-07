# Director Studio → GPU video-pipeline handoff (V1)

This contract closes the **planning-to-offline-GPU-plan** gap. Studio now
accepts browser-delivered verified MP4 clips for separate human review.
It does **not** constitute a live GPU dispatch or an automatic GPU-to-VPS
media push.

## 1. Studio owner-only workflow

1. Create/approve project output settings (resolution, fps, aspect), scene masters,
   prop masters when used, shot plans, storyboard images, and rough white-model
   records for the selected episode/shot. Character master approvals and shot
   bindings remain human controlled.
2. Open Video Production. The **per-shot readiness board** is sourced from
   the audited production DB. All 31 registered EP01 shots can be selected even
   when no video-plan record exists yet.
3. Save the video plan for a shot, including a **real motion prompt** and
   compatible duration/fps/width/height. Submit that plan for human review.
   Submitting is not approving a rendered clip.
4. Export **导出含来源校验的镜头制作单 JSON**. This calls the authenticated
   `GET /api/v1/workflow/video-package?project=...&episode=...&shot=...`
   endpoint and includes the versioned source records, references, blockers and
   SHA-256 over canonical JSON. Treat the package as private project material.

The package checksum detects accidental changes; it is **not an authenticated
signature**. Download through the authenticated Microsoft owner session and
transport via your secured operator-approved path. Do not expose this endpoint
anonymously or paste prompts, images or tokens in public issues.

## 2. GPU side — NO power-on or generation required for preparation

Once an operator already has the GPU-side persistent video-pipeline installed,
a real ComfyUI exported **API-format** H3 workflow, and true local node-field
bindings, copy the owner-exported Studio handoff JSON to an isolated directory
on that machine. On that GPU host, run:

```sh
python3 director_video.py prepare-studio \
  --package /safe/inbox/studio_handoff_EP01_SH01_V1.json \
  --workflow /safe/local/h3-workflow-api.json \
  --bindings /safe/local/h3-bindings.json \
  --out /safe/work/shot-01-plan.json
```

If the H3 graph uses an image binding, place the **approved source image** in
ComfyUI's locally controlled input folder and add `--image safe-name.png`.
The importer requires a basename, refuses traversal paths, checks the
Studio checksum, versioned approvals and shot duration/output specification,
then generates a local immutable plan for **one shot**. It does not connect to
ComfyUI or the VPS during preparation.

When GPU has been separately powered on with the owner's explicit approval,
the operator may run read-only preflight on the GPU:

```sh
python3 director_video.py preflight --plan /safe/work/shot-01-plan.json
```

Only after independently verifying cost, workflow, queue, image provenance and
permissions, the local runner retains its explicit two-flag opt-in:

```sh
python3 director_video.py submit --plan /safe/work/shot-01-plan.json \
  --db /safe/work/shot-01.sqlite --execute --acknowledge-gpu-cost --max-jobs 1
```

This command **can incur GPU charges**. Do not run it during read-only checks or
Studio deployment. Run collect/status afterward for generated output only if the
GPU executed it. There is currently **no live Studio→GPU dispatch button**.

## 3. Whole-episode preparation (31 shots; no silent omission)

The Studio Video Production page can export a private
`studio_episode_EP01_handoff.json` containing every registered shot, the
blocked-shot report, and a canonical SHA-256 over the bundle. To prepare the
entire episode locally, use:

```sh
python3 director_video.py prepare-studio-batch \
  --package /safe/inbox/studio_episode_EP01_handoff.json \
  --workflow /safe/local/h3-workflow-api.json \
  --bindings /safe/local/h3-bindings.json \
  --out /safe/work/episode-plan.json
```

If the H3 API graph uses image bindings, include an operator-reviewed
`--images /safe/local/approved-images.json` file whose keys are shot IDs
(e.g. `"01"`) and values are **local Comfy input basenames**. This importer
requires `all_ready=true`, a correctly hashed bundle, identical shot count
and IDs, consistent fps, no missing project approvals and exact total duration.
It fails closed instead of silently skipping blocked shots. The output is an
**offline pending queue plan**, not submitted jobs.

### Whole-episode delivery without 31 manual uploads

After separately approved local ComfyUI generation and
`director_video.py collect --download`, the GPU operator can create a
single *offline* folder from locally archived, per-shot checksum-verified MP4s:

```sh
python3 director_video.py export-studio-delivery \
  --plan /safe/work/episode-plan.json \
  --results /safe/work/collected-videos \
  --out /safe/work/StudioDelivery_EP01
```

This creates `manifest.json` and exactly one uniquely named MP4 per shot;
each entry pins the Studio project, episode, shot, video-plan revision,
original Studio package SHA-256, file SHA-256 and ComfyUI prompt ID.
The command checks all archive manifests and copied bytes and makes **zero**
network/GPU calls. Its checksum is **not a digital signature**.

Transfer that folder privately to the logged-in owner's local computer.
In Studio → Video Production → **整集视频批量回传**, select the folder
once (Chromium directory picker). The browser compares every entry with a
fresh, current owner-authenticated Studio episode bundle and streams one
file at a time using the already-protected video-result endpoints. Re-trying
the same folder resumes the 24-hour partial upload and skips exact immutable
clips already stored; it never doubles already approved assets or auto-approves
new clips. The directory contains project footage: avoid publishing it.

This is a **safe batch owner-mediated return**, not a headless GPU-to-VPS
network callback or GPU power operation. It does not change GPU permissions.

## 4. Verified MP4 return and formal human review

After a separately authorized GPU execution, use the existing local
`collect --download` to retrieve source clip bytes. In Studio select the
corresponding shot under Video Production and choose its real local MP4.
The owner-authorized browser workflow:

1. Obtains the current handoff SHA-256 for that same shot and revision.
2. Computes the source MP4 SHA-256 locally and starts a 24-hour resumable
   upload. Blocks are 786432 bytes (max file 250MB). Re-select the same file
   after a network interruption to resume rather than duplicate.
3. The VPS verifies the complete source hash, MP4 container, actual
   ffprobe width/height/fps/duration versus approved specs, and unchanged
   upstream creative assets. No server-side transcoding or GPU generation.
4. The verified immutable clip appears as an individual `video_take`
   in the Video Production player and unified Review Center. A human must
   explicitly approve or reject it with a reason. Revisions to upstream
   records prevent stale video approvals.

The MP4 API uses Microsoft owner authentication, CSRF/Origin checks for
writes, read authorization on every Range request, private file storage,
and no client-supplied output path. FFprobe is an installation prerequisite.

**Current uncrossed boundary:** automatic GPU-side push back to Studio is
not yet enabled. Source prompt IDs are operator metadata, not independent
cryptographic ComfyUI attestations. The local runner's archived output
manifests remain available to the operator for additional verification.
Live GPU queue compatibility, real H3 samples, audio work and final
assembled film still need independent acceptance tests.

The standard `studio/upgrade-v09.sh` deploys Studio backend/UI only; GPU
runner code changes are not thereby deployed to an offline GPU host. Do not
assume an already-installed GPU runner updated automatically.

## 4. Regression checks

- Studio: `python3 -m unittest discover -s studio/tests -p 'test_*.py' -v`
- GPU pipeline: `python3 -m unittest discover -s video-pipeline/tests -p 'test_*.py' -v`
- Browser workflow smoke: GitHub Actions Studio CI (headless Chromium, synthetic
  fixtures only; no production DB/GPU).
- Required security: owner-only GET, anonymous access denied, project-scoped
  lookup, no secret serialization, revision/stale checks, no GPU operation.
