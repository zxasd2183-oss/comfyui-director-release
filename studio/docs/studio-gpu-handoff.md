# Director Studio → GPU video-pipeline handoff (V1)

This contract closes the **planning-to-offline-GPU-plan** gap. It does **not**
constitute a live GPU dispatch, an approved render, or an MP4 feedback channel.

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

## 3. Current uncrossed boundary

GPU render result bytes, checked MP4 SHA-256 receipts, playback and formal
artistic approval are **not yet automatically returned to Studio**. The local
GPU runner already offers `collect --download`, verified output manifests and
`assemble`; a future authenticated result-import channel must link those
immutable files and their rendering provenance to the exact shot/plan revision
before any Studio UI may mark a video produced or approved.

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
