# ChatGPT → Director Studio · file synchronization (image MVP)

This integration is **source-only until installed on the VPS and the Director Hub connector refreshes**.

## Working flow

1. User creates an image in an active Studio-related ChatGPT conversation.
2. Once ChatGPT has an authorized file reference, the model calls
   `sync_chatgpt_visual_to_studio` with `project_id`, `episode_id`,
   `kind` (`character` / `scene` / `storyboard`), `subject_id`, and `file`.
3. ChatGPT supplies `file.download_url` and `file.file_id` as an official
   `_meta["openai/fileParams"]` tool parameter.
4. Director Hub downloads at most 8 MiB over DNS-pinned verified HTTPS,
   accepting tightly scoped OpenAI domains and the validated regional
   `oaisdmntpr<region>.blob.core.windows.net` storage-account family.
   Generic Azure Blob hosts, redirects, internal addresses and proxies remain blocked.
5. Hub signs the bytes for Studio's loopback-only ingestion endpoint using
   the existing Studio Brain Link HMAC secret, timestamp and replay nonce.
6. Studio atomically writes immutable file/source/audit records; same
   file/episode/subject retries are deduplicated. It displays the image in
   **EP01 → 图片素材库**. Selecting the *official* reference remains an
   owner action. Open Studio pages refresh this gallery at most once per
   four seconds (only when the inventory changed).
7. The existing authenticated Hub `get_production_episode` tool includes
   `visual_count` and bounded `visuals` for independent readback verification.
   The legacy `assets` table is distinct and may stay at zero even when
   the new image gallery contains pictures.

The file parameter must be **authorized by ChatGPT**. The model must never
invent a download URL or send a public URL to this tool. No GPU is invoked.

## Important limitations

- This does **not** automatically monitor every ChatGPT conversation, nor
  listen to a global "image generated" webhook. Automatic tool invocation is
  tied to an active, relevant conversation and accessible file reference.
- It does **not** automatically transfer a previously existing Library file
  unless ChatGPT can authorize and pass that file through the file parameter.
  An older file may need to be selected from the Library once.
- For this phase, only PNG, JPEG and WebP images up to 8 MiB are supported.
  Audio, video, PDFs, DOCX and other large assets require chunking and
  independent preview/metadata support. Do not label them synchronized.
- Text/shot plans can already use Director Hub's current production authoring
  tools, which are independent of this binary image sync.
- ChatGPT's Library is *not* a public list/download API for arbitrary VPS
  monitoring, and no permanent ChatGPT account credentials are stored.

## Owner VPS deployment

```bash
cd ~/comfyui-director-release
git pull --ff-only
sudo bash studio/upgrade-v09.sh
sudo bash vps-control/install-hub-v06.sh
```

Both installers perform local tests, backups, and service checks. The Hub
upgrade may refuse to proceed during a pending/executing GPU power approval
and must not be forced. This deployment does not start the GPU.

After successful installation, refresh/reconnect **Director Hub** in ChatGPT
so the 20th tool appears. It should expose
`sync_chatgpt_visual_to_studio` with `_meta["openai/fileParams"]=["file"]`.
Open `https://jipite.borealos.cn/studio/` in an owner-authenticated session
and view the EP01 image gallery.

## One-deployment acceptance checklist

Perform the two installers in the documented order, only after PR review and
CI success. Both services must be updated because Studio gains readback and
atomic ingestion while Hub gains pinned HTTPS regional downloads.

- Confirm all Studio and VPS GitHub CI jobs pass.
- Verify Hub exposes the same 20 tools; no power state transition.
- Retry **one** currently authorized ChatGPT image. A result is successful
  only when the Hub reports `ok: true` and `visual_id`, and a subsequent
  `get_production_episode` includes the exact `visual_id` under `visuals`.
- Compare Studio browser EP01 → 图片素材库 to the returned item. Confirm
  page auto-refresh within four seconds, and opening the image works.
- Repeat the same file once. Expect `unchanged: true`, identical
  `visual_id`, and no extra version or audit upload.
- Confirm the 31 shot durations, V1/V2 outline revision and GPU remain intact.
- If the URL expires or network delivery fails, report a bounded stage
  reason (DNS/TLS/HTTP/Studio); never print a signed download URL.
- If VPS outbound networking blocks Azure, a GitHub CI pass cannot prove
  production network reachability. Test from the authorized fileParam once
  after deployment and only then claim end-to-end production success.

Note: There is no general ChatGPT event hook notifying this MCP whenever
*any* content in *any* conversation is generated. File syncing depends on a
currently authorized active tool call. Text, PDFs, video and audio are not
implicitly included in this PNG/JPG/WebP pipeline.

## Security notes

- Studio media is owner-private and scoped to exact project and episode IDs.
- No external URL import in Studio; no cloud power/API credentials.
- Short-lived file URLs must never be placed in persistent logs.
- Media SHA-256 and append-only provenance are kept in Studio's private DB.
- Originals and prior version selections are never overwritten.
- Browser previews remain behind Studio Microsoft owner authentication.

## Follow-on phases

1. Generalized artifact store (docs, audio, video), chunked encrypted/verified
   transfer and streaming previews with per-type limits.
2. Retry/queue with event IDs and status in Studio, not invisible "success".
3. On-demand batch import from authorized ChatGPT Library files; not a covert
   global crawler.
4. Optionally direct custom ChatGPT app with file selector, still requiring
   access grants and never creating a universal conversation event hook.
