#!/usr/bin/env python3
"""Verify an approved private Studio MP4 against its owner-downloaded QC receipt.

Offline, read-only, no Studio credentials, GPU, networking or publication.
A SHA-256 receipt is an integrity checksum, NOT a signature or proof that an
untrusted third party authored the receipt. Obtain both files independently
through the authenticated Director Studio owner session.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

MAX_RECEIPT_BYTES = 32_768
MAX_MOVIE_BYTES = 16 * 1024**3
SHA = re.compile(r"^[0-9a-f]{64}$")
SCOPE = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
RELEASE = re.compile(r"^REL_[0-9a-f]{32}$")


class PrivateDeliveryError(ValueError):
    pass


def _fail(message):
    raise PrivateDeliveryError(message)


def _sha(value, name):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        _fail("invalid_" + name)
    return value


def _positive_int(value, name):
    if type(value) is not int or value < 1:
        _fail("invalid_" + name)
    return value


def _read_document(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        _fail("receipt_file_missing_or_symlink")
    if path.stat().st_size > MAX_RECEIPT_BYTES:
        _fail("receipt_too_large")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError):
        _fail("receipt_invalid_json")
    if not isinstance(doc, dict) or doc.get("ok") is not True:
        _fail("receipt_invalid_envelope")
    if doc.get("checksum_type") != "sha256_canonical_json_not_signature":
        _fail("receipt_checksum_contract_mismatch")
    receipt = doc.get("receipt")
    if not isinstance(receipt, dict):
        _fail("receipt_invalid_body")
    expected = _sha(doc.get("receipt_sha256"), "receipt_sha256")
    canonical = json.dumps(receipt, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != expected:
        _fail("receipt_checksum_mismatch")
    return receipt, expected


def _validate_receipt(receipt, *, project=None, episode=None, release=None):
    if receipt.get("schema") != "director_studio_private_delivery_receipt_v1":
        _fail("receipt_schema_unsupported")
    for name, expected in (("project_id", project), ("episode_id", episode)):
        value = receipt.get(name)
        if not isinstance(value, str) or not SCOPE.fullmatch(value):
            _fail("invalid_" + name)
        if expected is not None and value != expected:
            _fail(name + "_mismatch")
    uid = receipt.get("release_id")
    if not isinstance(uid, str) or not RELEASE.fullmatch(uid):
        _fail("invalid_release_id")
    if release is not None and uid != release:
        _fail("release_id_mismatch")
    if receipt.get("final_qc_status") != "approved":
        _fail("release_not_approved")
    # Reject an altered or future publication schema rather than implying
    # that a downloaded video is automatically cleared for distribution.
    for name in ("publicly_released", "external_distribution_authorized",
                 "signed_receipt"):
        if receipt.get(name) is not False:
            _fail("unsupported_receipt_permission_" + name)
    if receipt.get("subtitle_language") != "zh-CN":
        _fail("unexpected_subtitle_language")
    for name in ("mp4_sha256", "source_manifest_sha256", "av_master_sha256",
                 "subtitle_sha256"):
        _sha(receipt.get(name), name)
    if not isinstance(receipt.get("av_master_id"), str) or not receipt["av_master_id"]:
        _fail("invalid_av_master_id")
    if not isinstance(receipt.get("subtitle_id"), str) or not receipt["subtitle_id"]:
        _fail("invalid_subtitle_id")
    if not isinstance(receipt.get("reviewer"), str) or not receipt["reviewer"].strip():
        _fail("missing_final_reviewer")
    _positive_int(receipt.get("reviewed_at"), "reviewed_at")
    size = _positive_int(receipt.get("mp4_bytes"), "mp4_bytes")
    if size > MAX_MOVIE_BYTES:
        _fail("mp4_exceeds_verification_limit")
    duration = receipt.get("duration_seconds")
    if (isinstance(duration, bool) or not isinstance(duration, (int, float)) or
            not 0 < duration <= 86_400 or duration != duration):
        _fail("invalid_duration_seconds")
    return size


def _verify_movie(path, expected_size, expected_sha):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        _fail("mp4_missing_or_symlink")
    if path.stat().st_size != expected_size:
        _fail("mp4_size_mismatch")
    digest = hashlib.sha256()
    with path.open("rb") as media:
        if media.read(8)[4:8] != b"ftyp":
            _fail("mp4_container_header_invalid")
        media.seek(0)
        for chunk in iter(lambda: media.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha:
        _fail("mp4_checksum_mismatch")


def _check_streams(path, duration, ffprobe="ffprobe", runner=None):
    """Optional independent media stream check; no FFmpeg transcoding."""
    runner = subprocess.run if runner is None else runner
    try:
        result = runner([ffprobe, "-v", "error", "-show_entries",
                         "format=format_name,duration:stream=codec_type,codec_name",
                         "-of", "json", str(path)], capture_output=True,
                        check=True, timeout=30)
        info = json.loads(result.stdout)
        fmt = info["format"]
        streams = info["streams"]
        if not isinstance(fmt, dict) or not isinstance(streams, list):
            raise ValueError
        containers = fmt.get("format_name", "").split(",")
        if not ({"mp4", "mov"} & set(containers)):
            raise ValueError
        tracks = {}
        for item in streams:
            kind = item["codec_type"]
            tracks.setdefault(kind, []).append(item["codec_name"])
        if (len(tracks.get("video", [])) != 1 or
                len(tracks.get("audio", [])) != 1 or
                tracks["audio"][0] != "aac" or
                tracks.get("subtitle") != ["mov_text"]):
            raise ValueError
        actual = float(fmt["duration"])
        if not 0 < actual <= 86_400 or abs(actual - duration) > 0.75:
            raise ValueError
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
            KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError):
        _fail("mp4_ffprobe_stream_verification_failed")


def verify(receipt_path, movie_path, *, project=None, episode=None,
           release=None, check_streams=False, ffprobe="ffprobe", runner=None):
    """Return a deliberately limited integrity result for the two local files."""
    receipt, receipt_sha = _read_document(receipt_path)
    size = _validate_receipt(receipt, project=project, episode=episode,
                             release=release)
    _verify_movie(movie_path, size, receipt["mp4_sha256"])
    if check_streams:
        _check_streams(movie_path, receipt["duration_seconds"], ffprobe, runner)
    return {"ok": True, "project_id": receipt["project_id"],
            "episode_id": receipt["episode_id"], "release_id": receipt["release_id"],
            "mp4_sha256": receipt["mp4_sha256"], "receipt_sha256": receipt_sha,
            "bytes_verified": size, "streams_verified": bool(check_streams),
            "signed_receipt": False, "publication_authorized": False,
            "offline": True, "gpu_actions": 0, "network_calls": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify private Studio MP4 + QC receipt offline")
    parser.add_argument("--receipt", required=True, help="Owner-downloaded .json")
    parser.add_argument("--mp4", required=True, help="Owner-downloaded private .mp4")
    parser.add_argument("--project", help="Expected project ID")
    parser.add_argument("--episode", help="Expected episode ID")
    parser.add_argument("--release", help="Expected release ID")
    parser.add_argument("--check-streams", action="store_true",
                        help="Also require installed ffprobe and AAC + mov_text tracks")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args(argv)
    try:
        result = verify(args.receipt, args.mp4, project=args.project,
                        episode=args.episode, release=args.release,
                        check_streams=args.check_streams, ffprobe=args.ffprobe)
    except PrivateDeliveryError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True),
              file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
