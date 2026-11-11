"""Bounded, read-only EP01 final-assembly input inventory for Windows Worker.

No user-supplied paths, URLs or commands. This is an inventory, not a claim
of visual approvals, valid encoded clips or production render readiness.
"""
from __future__ import annotations

from pathlib import Path

from episode_final_assembler import (
    AssemblyError, SHOT_SECONDS, MAX_CLIP_BYTES, MAX_AUDIO_BYTES,
    _managed_path, _verify_wav,
)


def inspect_episode_inputs(workspace: Path) -> dict:
    """Return only fixed IDs and statuses; never expose filesystem paths."""
    workspace = Path(workspace).absolute()
    if not workspace.is_dir() or workspace.is_symlink() or getattr(workspace, 'is_junction', lambda: False)():
        return {"ok": False, "reason": "workspace_unavailable"}

    clip_root = workspace / "Outputs" / "EP01" / "Clips"
    missing, invalid, candidates = [], [], 0
    for number in range(1, len(SHOT_SECONDS) + 1):
        shot = f"{number:02d}"
        path = clip_root / ("SH" + shot + ".mp4")
        try:
            _managed_path(path, workspace, is_file=False)
            if not path.exists():
                missing.append(shot)
                continue
            if not path.is_file() or not 1024 <= path.stat().st_size <= MAX_CLIP_BYTES:
                invalid.append(shot)
                continue
            candidates += 1
        except (AssemblyError, OSError, ValueError):
            invalid.append(shot)

    audio = workspace / "Outputs" / "EP01" / "Audio" / "MixedAudio.wav"
    audio_status = "missing"
    try:
        _managed_path(audio, workspace, is_file=False)
        if audio.exists():
            if audio.is_file() and 0 < audio.stat().st_size <= MAX_AUDIO_BYTES:
                _verify_wav(audio)
                audio_status = "pcm_metadata_valid"
            else:
                audio_status = "invalid"
    except (AssemblyError, OSError, ValueError):
        audio_status = "invalid"

    output = workspace / "Outputs" / "EP01" / "Final" / "WaitingOffice_EP01_v001.mp4"
    output_status = "absent"
    try:
        _managed_path(output, workspace, is_file=False)
        if output.exists():
            output_status = "existing_file" if output.is_file() else "invalid"
    except (AssemblyError, OSError, ValueError):
        output_status = "invalid"

    all_present = not missing and not invalid and candidates == 31
    potential = all_present and audio_status == "pcm_metadata_valid" and output_status == "absent"
    return {
        "ok": True, "project_id": "WaitingOffice", "episode_id": "EP01",
        "fixed_shots": 31, "fixed_duration_seconds": 160,
        "clip_candidate_count": candidates, "missing_shot_ids": missing,
        "invalid_shot_ids": invalid, "mixdown_status": audio_status,
        "output_status": output_status,
        "input_inventory_complete": potential,
        "clips_codec_and_timing_verified": False,
        "artistic_approval_verified": False,
        "render_submitted": False,
        "note": "Inventory only. Exact clip decoding, full WAV, and all artistic approvals are separate gates.",
    }
