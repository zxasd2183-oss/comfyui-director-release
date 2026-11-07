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


## 5. Separate approved picture cut (local CPU, never GPU)

Once **every episode shot** has a human-approved current-source MP4, Studio
Video Production shows a full-episode picture-cut readiness count and the
exact source_manifest_sha256. A missing shot, stale revised upstream
asset, orphaned clip or unsupported stream combination blocks assembly.

After one-time deployment, the signed-in Microsoft owner can press
**一键生成整集画面初剪（本地 CPU）** in Video Production, review the
exact approved source digest and explicitly confirm local FFmpeg CPU use.
Studio creates an audited, persistent single-worker queue entry and
shows queued/running/done/failed state; service restarts can retry a
bounded number of times. No GPU, SSH approval or ComfyUI action occurs.
The resulting picture cut has a separate owner-review player and cannot
be labeled a final mastered movie.

For an independently reviewed terminal fallback, the operator can use
the local Studio service identity on the VPS. Assembly is separately
acknowledged, not part of deployment or GPU power operations:

    sudo -u directorstudio python3 /opt/director-studio/assemble_approved_cut.py \
      --db /var/lib/director-studio/production.sqlite \
      --project WaitingOffice --episode EP01 --check

After confirming the real manifest digest and accepting local CPU cost,
the operator may perform the separately acknowledged action:

    sudo -u directorstudio python3 /opt/director-studio/assemble_approved_cut.py \
      --db /var/lib/director-studio/production.sqlite \
      --project WaitingOffice --episode EP01 \
      --assemble --acknowledge-local-cpu \
      --expected-manifest-sha YOUR_EXACT_VERIFIED_64_HEX_DIGEST

The command rehashes all approved MP4s, verifies audio/video stream
compatibility with ffprobe, refuses missing/stale clips, then uses local
FFmpeg concat-copy without shell invocation. It validates the output,
publishes the immutable picture cut to the private Studio directory
and appends a tamper-evident audit event. Repeating the same approved
manifest returns the existing cut, never overwrites it.

The Microsoft-owner Studio picture-cut player displays the versioned
result for independent director approve/reject action. A picture cut
is **not a final release**: dubbing, effects, soundtrack, subtitles,
rights, loudness and mastering still need separate approval. Incompatible
source streams fail closed with picture_cut_streams_incompatible; the
system does not silently transcode or fabricate a finished film.


## 6. Rights-aware episode sound and private release

The Video Production workspace has three further independently approved
stages. They do NOT replace real H3/GPU model and media acceptance tests.

**Sound stems.** A signed-in Microsoft owner supplies three true, whole-
episode 48 kHz stereo PCM WAV recordings: dialogue/dubbing, licensed music,
and effects/ambience. Every WAV must match the episode duration to within
0.25 seconds. Each file is checked by SHA-256 and actual ffprobe format.
Authentication, per-owner resumable blocks, private storage and a 150 MB
limit apply. The owner must record a specific rights/consent provenance.
Human listening plus a separate rights confirmation are required to approve
each immutable revision. New versions supersede old approvals.

**CPU audio mix.** Only a current approved picture cut and the latest
approved version of all three WAV stems can be combined. After owner CPU
confirmation, a persistent serial worker copies the video stream, mixes
three tracks to stereo AAC at 48 kHz with loudness treatment targeted to
-16 LUFS and -1.5 dBTP, then validates the resulting MP4. Source SHA-256,
target SHA-256, stream format and approved source revisions are checked.
The result is queued for a distinct full-watch/full-listen human review
and rights approval; technical passing is not artistic endorsement.

**Subtitles.** Owner-uploaded SRT text is checked for a valid UTF-8 sequence,
numbered, monotonic, non-overlapping cues, accurate time syntax and boundaries
within the registered episode duration; markup and oversized files are
rejected. Separate subtitle language revisions and text provenance are
retained; approval requires independent script/rightsholder verification.
The initial release policy requires approved current Simplified Chinese SRT.

**Private release candidate.** A current approved A/V master and approved
current Chinese SRT may be packaged after an explicit local CPU confirmation.
FFmpeg preserves the approved video and audio streams and embeds the SRT as
MP4 mov_text. A source change aborts mux, and the output stream layout,
duration and SHA-256 are checked. The owner must separately sign off on
the full media, subtitle correctness, all rights/consents and actual
end-to-end playback before approving the private candidate.

No candidate is publicly released automatically. Other subtitle languages,
platform distribution, real H3 production, externally sourced sound licences,
and actual artistic acceptance need separate human verification. The GPU
remains stopped and this code is not yet deployed to VPS.

The single CPU worker serializes picture cuts, A/V mixing and subtitle mux
with durable audited job state, finite restart recovery and no GPU prompt
submission. These steps still depend on actual approved source content.


**Private delivery after QC:** An approved and still-current subtitled
candidate shows two owner-only download actions: the immutable MP4 and a
checksummed provenance/QC receipt. The receipt independently re-hashes the
current MP4 and confirms that approved picture, sound, subtitle versions
have not changed. It records original master and subtitle content digests,
reviewer and review timestamp; it is not a digital signature and does not
authorize external distribution. Neither download makes the video public.



## 新版 H3 逐镜头自动上传

Microsoft 所有者通过“视频制作”签发 48 小时短期剧集级回传凭据，
在 GPU 通过受保护的文件交给本地执行器。实际渲染后每个 MP4 自动
经独立的 HTTPS Nginx 上传通道传入 Studio，复用原有素材版本/尺寸/
SHA-256/FFprobe 验证，登记 \`in_review\`，不自动批准、不公开发布。

旧的浏览器整集导入保留为备用方案。
要使用自动回传，必须同时升级 Studio/Hub/VPS 与 GPU 本地执行器，
准备已审批的 H3 工作流/模型/镜头源图；单靠提交代码不会生成视频。
