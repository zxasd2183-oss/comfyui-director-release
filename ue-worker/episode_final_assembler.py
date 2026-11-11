"""Assemble a *real* EP01 MP4 only from 31 validated video clips and a mixed WAV.

This is an operator-side command line program, NOT an HTTP/MCP endpoint and
NOT a video generator. It will fail closed if any real shot or audio is missing.
It never launches a shell, downloads content, or writes outside --workspace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave

PROJECT = "WaitingOffice"
EPISODE = "EP01"
FPS = 24
WIDTH = 1080
HEIGHT = 1920
SECONDS = 160
FRAMES = FPS * SECONDS
SAMPLE_RATE = 48000
# Frozen Studio EP01 timeline (31 shots, 160 seconds). Do not modify.
SHOT_SECONDS = (
    3, 5, 5, 6, 6, 5, 5, 6, 5, 6, 5, 5,
    4, 5, 5, 5, 7, 5, 5, 5, 6, 5, 6, 5,
    4, 5, 5, 6, 5, 5, 5,
)
assert len(SHOT_SECONDS) == 31 and sum(SHOT_SECONDS) == SECONDS
MAX_CLIP_BYTES = 8 * 1024 ** 3
MAX_AUDIO_BYTES = SECONDS * SAMPLE_RATE * 2 * 4 + 100_000


class AssemblyError(ValueError):
    pass


def _managed_path(path: Path, root: Path, *, is_file: bool) -> Path:
    """Reject symlinks/junctions at every existing path component."""
    root = root.absolute()
    path = path.absolute()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AssemblyError("path_outside_workspace") from exc
    for part in (root, *list(path.parents)[::-1], path):
        if part.exists() and (part.is_symlink() or getattr(part, "is_junction", lambda: False)()):
            raise AssemblyError("managed_path_is_link")
    if is_file and (not path.is_file() or path.is_symlink()):
        raise AssemblyError("required_file_missing")
    return path


def _binary(name: str, env_name: str) -> str:
    specified = os.environ.get(env_name)
    binary = Path(specified) if specified else Path(shutil.which(name) or "")
    if not binary.is_file() or binary.name.lower() not in (name.lower(), name.lower()+".exe"):
        raise AssemblyError("missing_trusted_" + name)
    return str(binary)


def _probe(ffprobe: str, path: Path) -> dict:
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
           "-show_entries", "stream=codec_type,codec_name,width,height,avg_frame_rate,nb_read_frames,duration",
           "-of", "json", str(path)]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    if completed.returncode:
        raise AssemblyError("ffprobe_clip_failed")
    try:
        obj = json.loads(completed.stdout)
        streams = obj["streams"]
        if len(streams) != 1 or not isinstance(streams[0], dict):
            raise ValueError("missing stream")
        return streams[0]
    except (KeyError, ValueError, TypeError) as exc:
        raise AssemblyError("ffprobe_invalid_metadata") from exc


def _verify_video_meta(data: dict, duration_s: int, *, final: bool = False) -> None:
    if (data.get("codec_type") != "video" or data.get("width") != WIDTH or
            data.get("height") != HEIGHT or data.get("avg_frame_rate") != "24/1"):
        raise AssemblyError("video_dimensions_or_fps_mismatch")
    try:
        n = int(data["nb_read_frames"])
    except (ValueError, TypeError, KeyError) as exc:
        raise AssemblyError("video_frame_count_missing") from exc
    if n != duration_s * FPS:
        raise AssemblyError("video_frame_count_mismatch")
    # Video duration is checked against decoded frames, not MP4 container audio padding.
    try:
        length = float(data["duration"])
    except (ValueError, TypeError, KeyError) as exc:
        raise AssemblyError("video_duration_missing") from exc
    if not math.isfinite(length) or abs(length - duration_s) > 1.5 / FPS:
        raise AssemblyError("video_duration_mismatch")
    if final and data.get("codec_name") != "h264":
        raise AssemblyError("output_codec_mismatch")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_wav(path: Path) -> dict:
    if path.stat().st_size > MAX_AUDIO_BYTES:
        raise AssemblyError("wav_too_large")
    try:
        with wave.open(str(path), "rb") as f:
            if (f.getnchannels() != 2 or f.getframerate() != SAMPLE_RATE or
                    f.getsampwidth() not in (2, 3, 4) or
                    f.getcomptype() != "NONE" or f.getnframes() != SECONDS * SAMPLE_RATE):
                raise AssemblyError("mixdown_requires_160s_48khz_stereo_pcm")
            return {"channels": 2, "sample_rate": SAMPLE_RATE, "frames": f.getnframes()}
    except (wave.Error, EOFError) as exc:
        raise AssemblyError("invalid_mixdown_wav") from exc


def build_ffmpeg_command(ffmpeg: str, clips: list[Path], audio: Path, out: Path) -> list[str]:
    if len(clips) != len(SHOT_SECONDS):
        raise AssemblyError("clip_count_mismatch")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n"]
    for clip in clips:
        cmd.extend(["-i", str(clip)])
    cmd.extend(["-i", str(audio)])
    filters = []
    for i, duration in enumerate(SHOT_SECONDS):
        filters.append(
            f"[{i}:v]fps={FPS},trim=start_frame=0:end_frame={duration*FPS},"
            f"setpts=PTS-STARTPTS[v{i}]"
        )
    filters.append("".join(f"[v{i}]" for i in range(len(clips)))+f"concat=n={len(clips)}:v=1:a=0[v]")
    cmd.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[v]", "-map", f"{len(clips)}:a:0",
        "-frames:v", str(FRAMES), "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE), "-ac", "2",
        "-movflags", "+faststart", "-t", str(SECONDS), str(out),
    ])
    return cmd


def assemble(workspace: Path, ffmpeg: str, ffprobe: str, *, dry_run: bool = False) -> dict:
    workspace = workspace.absolute()
    if not workspace.is_dir() or workspace.is_symlink():
        raise AssemblyError("workspace_not_managed")
    clips_dir = _managed_path(workspace / "Outputs" / "EP01" / "Clips", workspace, is_file=False)
    audio = _managed_path(workspace / "Outputs" / "EP01" / "Audio" / "MixedAudio.wav", workspace, is_file=True)
    clips = []
    receipts = []
    for i, duration in enumerate(SHOT_SECONDS, 1):
        path = _managed_path(clips_dir / (f"SH{i:02d}.mp4"), workspace, is_file=True)
        size = path.stat().st_size
        if not 1024 <= size <= MAX_CLIP_BYTES:
            raise AssemblyError("clip_size_out_of_bounds")
        _verify_video_meta(_probe(ffprobe, path), duration)
        clips.append(path)
        receipts.append({"shot_id": f"{i:02d}", "frames": duration * FPS,
                         "bytes": size, "sha256": _sha256_file(path)})
    audio_meta = _verify_wav(audio)
    final_dir = _managed_path(workspace / "Outputs" / "EP01" / "Final", workspace, is_file=False)
    output = _managed_path(final_dir / "WaitingOffice_EP01_v001.mp4", workspace, is_file=False)
    pending = _managed_path(final_dir / "WaitingOffice_EP01_v001.partial.mp4", workspace, is_file=False)
    receipt_path = output.with_suffix(".receipt.json")
    if output.exists() or pending.exists() or receipt_path.exists():
        raise AssemblyError("output_or_receipt_already_exists")
    report = {"format": "director_episode_final_assembly_receipt_v1", "project_id": PROJECT,
              "episode_id": EPISODE, "fps": FPS, "resolution": [WIDTH, HEIGHT],
              "shots": receipts, "total_frames": FRAMES, "duration_seconds": SECONDS,
              "audio_meta": audio_meta, "status": "validated_not_rendered" if dry_run else "preparing"}
    if dry_run:
        return report
    final_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_ffmpeg_command(ffmpeg, clips, audio, pending)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=7200, check=False)
        if result.returncode:
            raise AssemblyError("ffmpeg_episode_encode_failed")
        if not pending.is_file():
            raise AssemblyError("ffmpeg_output_missing")
        _verify_video_meta(_probe(ffprobe, pending), SECONDS, final=True)
        output_digest = _sha256_file(pending)
        pending.replace(output)
    finally:
        if pending.exists():
            pending.unlink()
    report.update({"status": "encoded_video_track_and_audio_mix", "output_name": output.name,
                   "output_bytes": output.stat().st_size, "output_sha256": output_digest,
                   "note": "Visual/content QA and subtitle burn-in not asserted by this receipt"})
    receipt_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validated EP01 video/audio assembly (31 shots, 160s)")
    parser.add_argument("--workspace", type=Path, default=Path(os.getenv("DIRECTOR_UE_WORKSPACE", "C:/DirectorVirtualStudio")))
    parser.add_argument("--dry-run", action="store_true", help="validate all inputs only; does not encode")
    args = parser.parse_args(argv)
    try:
        report = assemble(args.workspace, _binary("ffmpeg", "DIRECTOR_FFMPEG_PATH"),
                          _binary("ffprobe", "DIRECTOR_FFPROBE_PATH"), dry_run=args.dry_run)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0
    except (AssemblyError, OSError, subprocess.SubprocessError) as exc:
        print("EP01 assembly failed closed: " + (str(exc) if isinstance(exc, AssemblyError) else "local_process_error"),file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
