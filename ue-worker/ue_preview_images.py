"""Read only fixed, SHA-pinned PNG frames from a completed UE preview job.

No external paths, directory listings, URL fetches, arbitrary filenames,
ZIP reads, GPU actions or rendering are available on this code path.
"""
from __future__ import annotations

import hashlib
import re
import struct

MAX_IMAGE_BYTES = 2 * 1024 * 1024
SHOTS = frozenset({"01", "13", "26", "31"})
PNG_HEADER = b"\x89PNG\r\n\x1a\n"
HASH = re.compile(r"[a-f0-9]{64}\Z")
JOB = re.compile(r"[a-f0-9]{32}\Z")


def _safe_directory(path):
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        return False
    return path.is_dir()


def get_preview_png(manager, job_id, shot_id):
    from ue_jobs import JobError

    if not isinstance(job_id, str) or not JOB.fullmatch(job_id):
        raise JobError("invalid_job_id")
    if not isinstance(shot_id, str) or shot_id not in SHOTS:
        raise JobError("invalid_preview_shot")
    record = manager.lookup(job_id)
    if (record.get("state") != "succeeded" or
            record.get("task") != "render_previs_stills" or
            record.get("project_id") != "WaitingOffice" or
            record.get("episode_id") != "EP01"):
        raise JobError("preview_job_not_completed")
    result = record.get("result")
    if type(result) is not dict or result.get("preview_count") != 4:
        raise JobError("preview_receipt_invalid")
    shots = result.get("screenshots")
    if type(shots) is not list or len(shots) != 4:
        raise JobError("preview_receipt_invalid")
    rows = [x for x in shots if type(x) is dict and x.get("shot_id") == shot_id]
    if len(rows) != 1:
        raise JobError("preview_receipt_invalid")
    row = rows[0]
    filename = f"WaitingOffice_EP01_SH{shot_id}_V03_V04_0000.png"
    relative = f"Outputs/V04/{job_id}/Previews/{filename}"
    if (row.get("filename") != filename or row.get("relative_path") != relative
            or type(row.get("bytes")) is not int
            or not 2048 <= row["bytes"] <= MAX_IMAGE_BYTES
            or type(row.get("sha256")) is not str
            or not HASH.fullmatch(row["sha256"])
            or row.get("width") != 720 or row.get("height") != 1280):
        raise JobError("preview_receipt_invalid")

    root = manager.root_factory()
    path = root
    for component in ("Outputs", "V04", job_id, "Previews"):
        path = path / component
        if not _safe_directory(path):
            raise JobError("preview_output_directory_unavailable")
    image = path / filename
    if (image.is_symlink() or getattr(image, "is_junction", lambda: False)()
            or not image.is_file() or image.stat().st_size != row["bytes"]):
        raise JobError("preview_image_unavailable")
    with image.open("rb") as file:
        data = file.read(MAX_IMAGE_BYTES + 1)
    if len(data) != row["bytes"] or len(data) > MAX_IMAGE_BYTES:
        raise JobError("preview_image_size_invalid")
    if (len(data) < 24 or data[:8] != PNG_HEADER or data[12:16] != b"IHDR"
            or struct.unpack(">II", data[16:24]) != (720, 1280)):
        raise JobError("preview_image_format_invalid")
    digest = hashlib.sha256(data).hexdigest()
    if digest != row["sha256"]:
        raise JobError("preview_image_hash_mismatch")
    return data, digest


# V1.1 read-only native MRQ PNGs of 5 authored UE Blueprint characters.
CAST_REVIEW_VIEWS = frozenset({"LINEUP","GPT","GEM","DS","CLA","ZERO"})
CAST_REVIEW_DIMENSIONS = {
    "LINEUP": (1280,720),
    "GPT": (720,1280), "GEM": (720,1280),
    "DS": (720,1280), "CLA": (720,1280), "ZERO": (720,1280),
}


def get_cast_review_png(manager, job_id, view):
    """Return only SHA-pinned Unreal-rendered frame from completed review.

    Non-permitted job types, manifests, user-specified paths, unknown views,
    symlinks, junctions, hash/dimension/length mismatches fail closed.
    """
    from ue_jobs import JobError
    if not isinstance(job_id,str) or not JOB.fullmatch(job_id):
        raise JobError("invalid_job_id")
    if not isinstance(view,str) or view not in CAST_REVIEW_VIEWS:
        raise JobError("invalid_cast_review_view")
    record=manager.lookup(job_id)
    if (record.get("state")!="succeeded" or
            record.get("task")!="render_cast_review_stills" or
            (record.get("project_id"),record.get("episode_id"))!=
            ("WaitingOffice","EP01")):
        raise JobError("cast_review_job_not_completed")
    result=record.get("result")
    if (type(result) is not dict or
            result.get("kind")!="actual_unreal_5_8_cast_mrq_review_v110" or
            result.get("preview_count")!=6 or
            result.get("source_cast_unchanged") is not True or
            result.get("character_masters_approved") is not False or
            result.get("final_film_rendered") is not False):
        raise JobError("cast_review_receipt_invalid")
    frames=result.get("screenshots")
    if (type(frames) is not list or len(frames)!=6 or
            {x.get("view") for x in frames if type(x) is dict}
            !=CAST_REVIEW_VIEWS):
        raise JobError("cast_review_receipt_invalid")
    selected=[x for x in frames if x["view"]==view]
    if len(selected)!=1:
        raise JobError("cast_review_receipt_invalid")
    row=selected[0]
    filename="WO_EP01_CAST_"+view+"_V11_0000.png"
    relative="Outputs/V11/"+job_id+"/Previews/"+filename
    dims=CAST_REVIEW_DIMENSIONS[view]
    if (type(row) is not dict or
            set(row)!={"view","filename","relative_path","bytes",
                       "sha256","width","height"} or
            row.get("filename")!=filename or
            row.get("relative_path")!=relative or
            type(row.get("bytes")) is not int or
            not 2048<=row["bytes"]<=MAX_IMAGE_BYTES or
            type(row.get("sha256")) is not str or
            not HASH.fullmatch(row["sha256"]) or
            (row.get("width"),row.get("height"))!=dims):
        raise JobError("cast_review_receipt_invalid")
    path=manager.root_factory()
    for component in ("Outputs","V11",job_id,"Previews"):
        path=path/component
        if not _safe_directory(path):
            raise JobError("cast_review_image_directory_invalid")
    png=path/filename
    if (png.is_symlink() or getattr(png,"is_junction",lambda:False)()
            or not png.is_file() or png.stat().st_size!=row["bytes"]):
        raise JobError("cast_review_png_unavailable")
    with png.open("rb") as file:
        data=file.read(MAX_IMAGE_BYTES+1)
    if (len(data)!=row["bytes"] or len(data)<24 or
            data[:8]!=PNG_HEADER or data[12:16]!=b"IHDR" or
            struct.unpack(">II",data[16:24])!=dims or
            hashlib.sha256(data).hexdigest()!=row["sha256"]):
        raise JobError("cast_review_png_integrity_failed")
    return data,row["sha256"]
