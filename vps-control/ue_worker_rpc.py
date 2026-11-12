"""Fail-closed VPS -> Windows UE Worker adapter.

Pinned to the VPS loopback end of the dedicated SSH reverse tunnel.
Never accepts a remote URL or arbitrary operation from an MCP caller.
"""
from __future__ import annotations

import json
import os
import re
import stat
import urllib.error
import urllib.request
from pathlib import Path

WORKER_ORIGIN = "http://127.0.0.1:18910"
READ_ROUTES = {
    "get_ue_worker_status": "/v1/status",
    "get_ue_worker_capabilities": "/v1/capabilities",
    "get_ue_episode_assembly_readiness": "/v6/episode/assembly-readiness",
}
WRITE_ACTIONS = {"prepare_ue_workspace": "prepare_workspace"}
MAX_RESULT = 16384


class WorkerError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise WorkerError("redirect_not_allowed")


OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirect()
)


def load_token(path=None):
    path = Path(path or os.getenv("DIRECTOR_UE_WORKER_TOKEN_FILE",
                                "/etc/director-ue-worker.token"))
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 128:
        raise WorkerError("worker_token_unconfigured")
    if stat.S_IMODE(path.stat().st_mode) & 0o007:
        raise WorkerError("insecure_token_permissions")
    token = path.read_text("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise WorkerError("invalid_worker_token")
    return token


def call_ue_worker(name, opener=None, token_file=None):
    """Only three known actions; do not relay arbitrary paths, commands or args."""
    if name not in READ_ROUTES and name not in WRITE_ACTIONS:
        return {"ok": False, "reason": "action_denied"}
    if os.getenv("DIRECTOR_UE_WORKER_ENABLED", "0") != "1":
        return {"ok": False, "reason": "ue_worker_not_enabled"}
    try:
        token = load_token(token_file)
        if name in READ_ROUTES:
            path, data, method = READ_ROUTES[name], None, "GET"
        else:
            path, method = "/v1/actions", "POST"
            data = json.dumps({"action": WRITE_ACTIONS[name]}).encode("ascii")
        url = WORKER_ORIGIN + path
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        with (opener or OPENER).open(req, timeout=8) as response:
            if response.geturl() != url:
                raise WorkerError("redirect_not_allowed")
            raw = response.read(MAX_RESULT + 1)
        if len(raw) > MAX_RESULT:
            raise WorkerError("worker_response_too_large")
        obj = json.loads(raw)
        if not isinstance(obj, dict) or type(obj.get("ok")) is not bool:
            raise WorkerError("invalid_worker_response")
        return obj
    except WorkerError as exc:
        return {"ok": False, "reason": str(exc)}
    except (OSError, TypeError, ValueError, urllib.error.URLError):
        return {"ok": False, "reason": "ue_worker_unavailable"}


# V0.2: only fixed, Studio-derived timeline jobs. No caller-supplied paths.
STUDIO_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,47}$")
JOB_ID = re.compile(r"^[a-f0-9]{32}$")


def _v2_request(path, method="GET", body=None, opener=None, token_file=None):
    if os.getenv("DIRECTOR_UE_WORKER_ENABLED", "0") != "1":
        return {"ok": False, "reason": "ue_worker_not_enabled"}
    try:
        token = load_token(token_file)
        url = WORKER_ORIGIN + path
        payload = None if body is None else json.dumps(
            body, separators=(",", ":")
        ).encode("utf-8")
        if payload is not None and len(payload) > 24576:
            return {"ok": False, "reason": "request_too_large"}
        request = urllib.request.Request(
            url, data=payload, method=method,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        with (opener or OPENER).open(request, timeout=10) as response:
            if response.geturl() != url:
                raise WorkerError("redirect_not_allowed")
            raw = response.read(MAX_RESULT + 1)
        if len(raw) > MAX_RESULT:
            raise WorkerError("worker_response_too_large")
        decoded = json.loads(raw)
        if not isinstance(decoded, dict) or type(decoded.get("ok")) is not bool:
            raise WorkerError("invalid_worker_response")
        return decoded
    except WorkerError as exc:
        return {"ok": False, "reason": str(exc)}
    except urllib.error.HTTPError as exc:
        # Preserve authenticated Worker 4xx reasons, not a misleading
        # network-down error. Never echo unbounded/unsanitized HTML.
        try:
            raw = exc.read(MAX_RESULT + 1)
            if len(raw) > MAX_RESULT:
                raise ValueError("large_error_response")
            decoded = json.loads(raw)
            if (type(decoded) is dict and decoded.get("ok") is False
                    and type(decoded.get("reason")) is str
                    and re.fullmatch(r"[a-z0-9_]{1,80}", decoded["reason"])):
                return {"ok": False, "reason": decoded["reason"],
                        "worker_http_status": exc.code}
        except (OSError, TypeError, ValueError, UnicodeError):
            pass
        return {"ok": False, "reason": "ue_worker_rejected_request",
                "worker_http_status": exc.code}
    except (OSError, TypeError, ValueError, urllib.error.URLError):
        return {"ok": False, "reason": "ue_worker_unavailable"}


def enqueue_ue_episode_timeline(project_id, episode_id, studio_getter=None,
                                opener=None, token_file=None,
                                task="build_episode_timeline"):
    """Obtain immutable ordered shot metadata from Studio, never from the caller."""
    if not all(isinstance(v, str) and STUDIO_ID.fullmatch(v)
               for v in (project_id, episode_id)):
        return {"ok": False, "reason": "invalid_identifiers"}
    if task not in ("build_episode_timeline", "build_stage_cameras",
                    "render_previs_stills", "audit_ep01_assets",
                    "build_ep01_scene_candidates",
                    "build_ep01_cast_blueprints",
                    "render_cast_review_stills"):
        return {"ok": False, "reason": "task_not_allowlisted"}
    if os.getenv("DIRECTOR_UE_WORKER_ENABLED", "0") != "1":
        return {"ok": False, "reason": "ue_worker_not_enabled"}
    if studio_getter is None:
        from hub_brain import call_studio
        studio_getter = call_studio
    try:
        episode = studio_getter(
            "get_production_episode",
            {"project_id": project_id, "episode_id": episode_id}
        )
        if (type(episode) is not dict or not episode.get("ok") or
                episode.get("shots_truncated") or
                not isinstance(episode.get("shots"), list) or
                not 1 <= len(episode["shots"]) <= 150 or
                episode.get("shot_count") != len(episode["shots"])):
            return {"ok": False, "reason": "studio_plan_unavailable"}
        shots = sorted(episode["shots"], key=lambda item: item["ordinal"])
        registered = [
            {
                "shot_id": item["shot_id"],
                "ordinal": item["ordinal"],
                "duration_ms": item["duration_ms"],
            } for item in shots
        ]
        if any(type(s["duration_ms"]) is not int for s in registered):
            raise ValueError("invalid duration")
        total = sum(s["duration_ms"] for s in registered)
        spec = {
            "task": task,
            "project_id": project_id,
            "episode_id": episode_id,
            "fps": 24,  # EP01's locked cinematic plan
            "shots": registered,
            "expected_total_ms": total,
        }
        response = _v2_request("/v2/jobs", "POST", spec, opener, token_file)
        if response.get("ok"):
            response["source"] = "Director Studio registered shots"
        return response
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "reason": "studio_plan_invalid"}


def get_ue_episode_job_status(job_id, opener=None, token_file=None):
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        return {"ok": False, "reason": "invalid_job_id"}
    return _v2_request("/v2/jobs/" + job_id, "GET", None, opener, token_file)


def enqueue_ue_stage_cameras(project_id, episode_id, studio_getter=None,
                             opener=None, token_file=None):
    """Generate V03 assets from Studio's frozen episode. No arbitrary scene paths."""
    if (project_id, episode_id) != ("WaitingOffice", "EP01"):
        return {"ok": False, "reason": "v03_stage_requires_locked_ep01"}
    return enqueue_ue_episode_timeline(
        project_id, episode_id, studio_getter=studio_getter,
        opener=opener, token_file=token_file, task="build_stage_cameras",
    )


def enqueue_ue_previs_stills(project_id, episode_id, studio_getter=None,
                            opener=None, token_file=None):
    """Render exactly four fixed PNG stills using V03 map and Studio shot plan.

    Requires an existing V03 stage/cameras; consumes metered GPU time.
    Clients cannot supply paths, shots, output settings or render scripts.
    """
    if (project_id, episode_id) != ("WaitingOffice", "EP01"):
        return {"ok": False, "reason": "v04_previs_requires_locked_ep01"}
    return enqueue_ue_episode_timeline(
        project_id, episode_id, studio_getter=studio_getter,
        opener=opener, token_file=token_file, task="render_previs_stills",
    )


def enqueue_ue_asset_audit(project_id, episode_id, studio_getter=None,
                           opener=None, token_file=None):
    """Read native Unreal assets for all fixed EP01 production dependencies.

    Never receive caller-supplied asset paths, code, URLs or render options.
    This job is a technical inventory, NOT an artistic approval or render.
    """
    if (project_id, episode_id) != ("WaitingOffice", "EP01"):
        return {"ok": False, "reason": "asset_audit_requires_locked_ep01"}
    return enqueue_ue_episode_timeline(
        project_id, episode_id, studio_getter=studio_getter,
        opener=opener, token_file=token_file, task="audit_ep01_assets",
    )


def enqueue_ue_scene_candidates(project_id, episode_id,
                                studio_getter=None, scene_getter=None,
                                opener=None, token_file=None):
    """Build three original UE environment draft Worlds from fixed EP01 layout.

    Require both scene draft IDs to exist in Studio; never accept authored
    scripts/asset paths or interpret draft status as approval.
    """
    if (project_id, episode_id) != ("WaitingOffice", "EP01"):
        return {"ok": False, "reason": "scene_candidates_require_locked_ep01"}
    if scene_getter is None:
        from hub_brain import call_studio
        scene_getter = call_studio
    try:
        record = scene_getter("get_production_scenes", {"project_id": project_id})
        items = record.get("scenes") if type(record) is dict and record.get("ok") is True else None
        if (type(items) is not list or
                not {"SCN-HALL", "SCN-ENTRANCE"} <= {
                    row.get("scene_id") for row in items if type(row) is dict
                }):
            return {"ok": False, "reason": "studio_scene_drafts_missing"}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"ok": False, "reason": "studio_scene_drafts_unavailable"}
    return enqueue_ue_episode_timeline(
        project_id, episode_id, studio_getter=studio_getter,
        opener=opener, token_file=token_file, task="build_ep01_scene_candidates",
    )


def enqueue_ue_cast_blueprints(project_id, episode_id,
                               studio_getter=None, cast_getter=None,
                               opener=None, token_file=None):
    """Build 5 ORIGINAL actor Blueprint design candidates, not MetaHumans.

    Five fixed Studio role identities are mandatory. No caller-supplied
    screenshots, scripts, paths, logos, or content references reach Worker.
    """
    if (project_id,episode_id) != ("WaitingOffice","EP01"):
        return {"ok":False,"reason":"cast_requires_locked_ep01"}
    if cast_getter is None:
        from hub_brain import call_studio
        cast_getter=call_studio
    try:
        record=cast_getter("get_project_characters",{"project_id":project_id})
        rows=record.get("characters") if type(record) is dict and record.get("ok") is True else None
        expected={"CHAR_GPT","CHAR_GEM","CHAR_DS","CHAR_CLA","CHAR_ZERO"}
        if (type(rows) is not list or
                {row["character_id"] for row in rows
                 if type(row) is dict and row.get("role")=="main"
                 and type(row.get("character_id")) is str} != expected):
            return {"ok":False,"reason":"studio_main_cast_registry_mismatch"}
    except (KeyError,ValueError,TypeError,AttributeError):
        return {"ok":False,"reason":"studio_main_cast_unavailable"}
    return enqueue_ue_episode_timeline(
        project_id,episode_id,studio_getter=studio_getter,
        opener=opener,token_file=token_file,
        task="build_ep01_cast_blueprints",
    )


def enqueue_ue_cast_review(project_id,episode_id,
                           studio_getter=None,cast_getter=None,
                           opener=None,token_file=None):
    """Render six verified genuine UE MRQ images of pinned V1.0 Blueprints.

    No caller paths, images, camera settings, arbitrary scripts or URLs.
    Registered Studio cast IDs gate the fixed render task.
    """
    if (project_id,episode_id)!=("WaitingOffice","EP01"):
        return {"ok":False,"reason":"cast_review_requires_locked_ep01"}
    if cast_getter is None:
        from hub_brain import call_studio
        cast_getter=call_studio
    try:
        data=cast_getter("get_project_characters",{"project_id":project_id})
        rows=data.get("characters") if type(data) is dict and data.get("ok") is True else None
        expected={"CHAR_GPT","CHAR_GEM","CHAR_DS","CHAR_CLA","CHAR_ZERO"}
        if (type(rows) is not list or
                {row["character_id"] for row in rows
                 if type(row) is dict and row.get("role")=="main"
                 and type(row.get("character_id")) is str}!=expected):
            return {"ok":False,"reason":"studio_main_cast_registry_mismatch"}
    except (KeyError,ValueError,TypeError,AttributeError):
        return {"ok":False,"reason":"studio_main_cast_unavailable"}
    return enqueue_ue_episode_timeline(
        project_id,episode_id,studio_getter=studio_getter,
        opener=opener,token_file=token_file,
        task="render_cast_review_stills",
    )


# V0.5 operator workflow: job-bound log tails and task cancellation only.
# No caller-supplied filenames, PIDs, shell commands, or arbitrary URLs.
LOG_KIND = frozenset({
    "unreal", "preset", "render_01", "render_13",
    "render_26", "render_31",
})


def get_ue_job_logs(job_id, kind, opener=None, token_file=None):
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        return {"ok": False, "reason": "invalid_job_id"}
    if not isinstance(kind, str) or kind not in LOG_KIND:
        return {"ok": False, "reason": "invalid_log_kind"}
    return _v2_request(
        "/v3/jobs/" + job_id + "/logs/" + kind,
        "GET", None, opener, token_file,
    )


def cancel_ue_job(job_id, opener=None, token_file=None):
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        return {"ok": False, "reason": "invalid_job_id"}
    # Empty POST: Worker rejects any request payload on this route.
    return _v2_request(
        "/v3/jobs/" + job_id + "/cancel",
        "POST", None, opener, token_file,
    )


# V0.5.2: exact one-frame image forwarding over the existing private SSH
# tunnel. This is deliberately separate from bounded JSON job-status RPCs.
PREVIEW_SHOTS = frozenset({"01", "13", "26", "31"})
MAX_PREVIEW_PNG = 2 * 1024 * 1024
PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def get_ue_preview_png(job_id, shot_id, opener=None, token_file=None):
    """Return verified raw PNG bytes internally, never a filesystem path/URL."""
    import hashlib
    import struct

    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        return {"ok": False, "reason": "invalid_job_id"}
    if not isinstance(shot_id, str) or shot_id not in PREVIEW_SHOTS:
        return {"ok": False, "reason": "invalid_preview_shot"}
    if os.getenv("DIRECTOR_UE_WORKER_ENABLED", "0") != "1":
        return {"ok": False, "reason": "ue_worker_not_enabled"}
    try:
        token = load_token(token_file)
        url = WORKER_ORIGIN + "/v5/jobs/" + job_id + "/previews/" + shot_id
        request = urllib.request.Request(url, method="GET", headers={
            "Authorization": "Bearer " + token,
            "Accept": "image/png",
        })
        with (opener or OPENER).open(request, timeout=15) as response:
            if response.geturl() != url:
                raise WorkerError("redirect_not_allowed")
            if response.headers.get("Content-Type") != "image/png":
                raise WorkerError("preview_mime_mismatch")
            declared = response.headers.get("Content-Length")
            if (declared is None or not declared.isdecimal()
                    or not 2048 <= int(declared) <= MAX_PREVIEW_PNG):
                raise WorkerError("preview_length_invalid")
            expected_digest = response.headers.get("X-Director-PNG-SHA256")
            if not isinstance(expected_digest, str) or not re.fullmatch(
                r"[a-f0-9]{64}", expected_digest
            ):
                raise WorkerError("preview_digest_header_invalid")
            data = response.read(MAX_PREVIEW_PNG + 1)
        if len(data) != int(declared) or len(data) > MAX_PREVIEW_PNG:
            raise WorkerError("preview_size_mismatch")
        if (len(data) < 24 or data[:8] != PNG_HEADER
                or data[12:16] != b"IHDR"
                or struct.unpack(">II", data[16:24]) != (720, 1280)):
            raise WorkerError("preview_png_invalid")
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected_digest:
            raise WorkerError("preview_hash_mismatch")
        return {"ok": True, "data": data, "sha256": digest,
                "job_id": job_id, "shot_id": shot_id}
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(1025)
            info = json.loads(raw)
            if (len(raw) <= 1024 and type(info) is dict
                    and info.get("ok") is False
                    and type(info.get("reason")) is str
                    and re.fullmatch(r"[a-z0-9_]{1,80}", info["reason"])):
                return {"ok": False, "reason": info["reason"]}
        except (OSError, ValueError, UnicodeError, TypeError):
            pass
        return {"ok": False, "reason": "preview_worker_http_error"}
    except WorkerError as exc:
        return {"ok": False, "reason": str(exc)}
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return {"ok": False, "reason": "ue_worker_unavailable"}
# The public MCP bridge rejects responses larger than 1 MiB. A verified
# 720x1280 PNG can exceed this once portrait pixels fill the full frame
# (Base64 alone adds ~33%). Return an explicitly labeled VIEW thumbnail,
# never alter the SHA-pinned original PNG on the RTX 4090.
def make_bounded_preview_thumbnail_png(original):
    """Safely decode fixed-size RGB/RGBA PNG and return a <=512KiB PNG.

    No filesystem paths, shell, arbitrary URL, optional Pillow dependency,
    or source asset edits. The call site MUST first run get_ue_preview_png,
    which validates the authoritative Worker receipt SHA-256.
    """
    import binascii
    import struct
    import zlib

    def fail():
        raise WorkerError("preview_thumbnail_invalid_png")

    if (type(original) is not bytes or
            not 2048 <= len(original) <= MAX_PREVIEW_PNG or
            not original.startswith(PNG_HEADER)):
        fail()

    pos = 8
    chunks = 0
    compressed = bytearray()
    image_info = None
    has_end = False
    while pos + 12 <= len(original) and chunks < 128:
        size = struct.unpack_from(">I", original, pos)[0]
        kind = original[pos + 4:pos + 8]
        end = pos + 12 + size
        if size > MAX_PREVIEW_PNG or end > len(original):
            fail()
        body = original[pos + 8:pos + 8 + size]
        crc = struct.unpack_from(">I", original, pos + 8 + size)[0]
        if (binascii.crc32(kind + body) & 0xffffffff) != crc:
            fail()
        chunks += 1
        if kind == b"IHDR":
            if image_info is not None or chunks != 1 or size != 13:
                fail()
            w, h, depth, col, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", body
            )
            if ((w, h) != (720, 1280) or depth != 8 or col not in (2, 6)
                    or compression or filtering or interlace):
                fail()
            image_info = (w, h, 3 if col == 2 else 4, col)
        elif kind == b"IDAT":
            if image_info is None or has_end:
                fail()
            compressed.extend(body)
            if len(compressed) > MAX_PREVIEW_PNG:
                fail()
        elif kind == b"IEND":
            if size != 0 or image_info is None or not compressed or end != len(original):
                fail()
            has_end = True
            break
        elif kind in (b"PLTE", b"tRNS") or (kind[0] & 32) == 0:
            # Fixed truecolor image: no palette or other unknown critical chunks.
            fail()
        pos = end
    if not has_end or image_info is None:
        fail()

    width, height, channels, color_type = image_info
    stride = width * channels
    expected = height * (stride + 1)
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(bytes(compressed), expected + 1)
    except zlib.error as exc:
        raise WorkerError("preview_thumbnail_bad_deflate") from exc
    if (len(raw) != expected or not decoder.eof or decoder.unconsumed_tail
            or decoder.unused_data):
        fail()

    rows = []
    prev = bytearray(stride)
    offset = 0
    for _ in range(height):
        method = raw[offset]
        offset += 1
        if method > 4:
            fail()
        row = bytearray(raw[offset:offset + stride])
        offset += stride
        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            up = prev[i]
            ul = prev[i - channels] if i >= channels else 0
            if method == 1:
                predictor = left
            elif method == 2:
                predictor = up
            elif method == 3:
                predictor = (left + up) // 2
            elif method == 4:
                p = left + up - ul
                a, b, c = abs(p - left), abs(p - up), abs(p - ul)
                predictor = left if a <= b and a <= c else (up if b <= c else ul)
            else:
                predictor = 0
            row[i] = (row[i] + predictor) & 0xff
        rows.append(row)
        prev = row

    def png_chunk(kind, contents):
        length = struct.pack(">I", len(contents))
        crc = struct.pack(">I", binascii.crc32(kind + contents) & 0xffffffff)
        return length + kind + contents + crc

    # Source PNGs are 720x1280. 2x downsampling produces a useful
    # 360x640 visual. If compression is unexpectedly poor, 4x is always
    # below our conservative 512KiB MCP bridge budget even for RGBA noise.
    for factor in (2, 4):
        tw, th = width // factor, height // factor
        scanlines = bytearray()
        for y in range(0, height, factor):
            row = rows[y]
            scanlines.append(0)  # unfiltered output row
            for x in range(0, width, factor):
                at = x * channels
                scanlines.extend(row[at:at + channels])
        packed = zlib.compress(bytes(scanlines), level=6)
        output = (PNG_HEADER +
                  png_chunk(b"IHDR", struct.pack(
                      ">IIBBBBB", tw, th, 8, color_type, 0, 0, 0
                  )) + png_chunk(b"IDAT", packed) + png_chunk(b"IEND", b""))
        if len(output) <= 512 * 1024:
            return output
    raise WorkerError("preview_thumbnail_bridge_budget_exceeded")


def choose_mcp_preview_png(original):
    """Preserve small original PNGs; resize large ones within 1MiB MCP JSON.

    The caller has already SHA256-validated the original via the private
    Worker. Any derived PNG is for visual inspection only, never a
    replacement for the source image or authoritative receipt.
    """
    if type(original) is not bytes:
        raise WorkerError("preview_image_invalid_bytes")
    if len(original) <= 512 * 1024:
        return original
    return make_bounded_preview_thumbnail_png(original)


# V0.6 signed update controls: caller cannot supply code, version or URL.
def get_ue_signed_update_status(opener=None, token_file=None):
    return _v2_request("/v4/update/status", "GET", None, opener, token_file)


def request_ue_signed_update(opener=None, token_file=None):
    """Queue a check on the NEXT privileged signed-updater poll, not an install."""
    return _v2_request("/v4/update/request", "POST", None, opener, token_file)
