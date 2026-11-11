# UE Worker V0.5.2 — direct preview-image viewing in ChatGPT

## Goal

The V0.5.1 Windows UE 5.8 render job
`a7fcd4fe34e849248b7664bc717aa67b` already **succeeded**, creating
SH01 / SH13 / SH26 / SH31 real 720×1280 PNG files with a complete
SHA-256 receipt. V0.5.2 adds the missing, **read-only** operator path so
ChatGPT can inspect the original pixels over the existing SSH tunnel.

## One image at a time

ChatGPT: `get_ue_preview_image(job_id, shot_id)`. Use only these shot IDs:
`01`, `13`, `26`, `31`. The tool returns **native MCP PNG image
content** (not a placeholder, external URL, base64 text blob, or JSON
filename). The assistant can directly view and compare the frames.

Data path:

```
ChatGPT / Director Hub MCP get_ue_preview_image
  -> VPS private loopback :18910
  -> existing SSH reverse tunnel
  -> Windows Worker :19010 /v5/jobs/<job_id>/previews/<shot_id>
  -> one exact SHA-verified PNG from the completed job
```

### Exact safety constraints

- The original bearer token continues to be required on the Windows Worker.
- A job must be a **succeeded** `render_previs_stills` run of
  `WaitingOffice / EP01`, with a completed four-image receipt.
- The caller can provide only a 32-character lowercase hex job ID and
  one of four **literal** shot identifiers.
- The Worker constructs a fixed `Outputs/V04/<job_id>/Previews/`
  filename. No path, URL, package name, command, or other filename is
  accepted. It rejects symlinked/junction output directories and images.
- Original PNG **bytes, size, SHA-256 and 720×1280 dimensions** must
  match the saved job receipt. Transfer capped at 2 MiB, no redirects,
  no proxy, private tunnel only, `Content-Type: image/png`, `nosniff`,
  `Cache-Control: no-store`.
- VPS checks PNG MIME, length, header and digest again before
  producing the native MCP image object.
- This endpoint **cannot start a render or modify assets**. It never
  publishes publicly accessible download links.
- It does not bypass ChatGPT's existing plugin authentication, and does
  not make arbitrary files on the user's computer available.

## Required one-time rollout for this version

1. Confirm no active UE jobs; keep the current V0.5.1 asset and code backups.
2. Upgrade **Windows** Worker using the reviewed
   `ue-worker/install-v052.ps1` script from this entire branch
   checkout, in the same elevated Windows administrative context used
   for the previous successful V0.5.1 rollout. It retains the dedicated
   non-admin Worker task, existing bearer token, VPS tunnel and all UE
   asset folders; it backs up code and rolls back on failed health.
3. Upgrade **VPS** `ue_worker_rpc.py` and `hub_app.py` from the SAME
   branch via the existing guarded Hub deployment mechanism. Restart
   only `director-hub-mcp` (and its existing discoverer if required)
   — not all unrelated services.
4. Verify Worker reports `0.5.2`, tool
   `get_ue_preview_image` appears in the Hub tool list, and the first
   real PNG successfully loads. A fresh ChatGPT Director Hub app
   invocation may be needed for tool discovery.
5. From ChatGPT, call `get_ue_preview_image` for the four shot IDs of
   job `a7fcd4fe34e849248b7664bc717aa67b`. Inspect saturation,
   retained wall/floor/table detail, SH13 framing and distinct camera
   perspectives. Do **not** rerender merely to read these files.

## Original run receipt

- V0.5.1 job: `a7fcd4fe34e849248b7664bc717aa67b`
- Result: `succeeded`, `preview_count=4`
- Source V03 stage `source_stage_unchanged=true`
- V03 map SHA-256 (verified by worker):
  `7fac6dd780409aef1db577504e145d390fa62f6c39fd160c6d7c122f7ff2f488`
- SH01 SHA-256:
  `cc0bfa6b3481589fd06b781f6cf788e83bd8a01a9e5fdae5c1436a8620d44918`
- SH13 SHA-256:
  `7213e5184ba38409f64682277c080c5acdb8ffe99b00a30bea1c050d2626c7dd`
- SH26 SHA-256:
  `f85c926bd3fc8d419e861a53dde4b4a07ac20e6f547d1762ab4f6e9af31089fc`
- SH31 SHA-256:
  `da9c333512634e066a046f9e5aa430ba1b2a4aa12bbf45e281377414b18c2199`

### What this is NOT

The CI tests use synthetic, non-rendered PNG fixtures. The **actual**
V0.5.1 frames already exist on Windows. V0.5.2 image-transport tests
cannot establish whether lighting and composition are visually
acceptable until the real images are fetched and inspected.
