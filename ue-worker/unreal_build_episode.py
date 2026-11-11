"""Trusted Unreal Editor commandlet script: generate one episode's Sequencer assets.

Executed ONLY by ue_jobs.py with a validated local job manifest. This code runs
inside Unreal Editor Python, not the Windows worker's normal Python process.
The sequences are timing-only placeholders; camera, actor and audio bindings
must be added in later production stages before rendering.
"""
from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

import unreal


def create_if_missing(asset_tools, name, package):
    full = package + "/" + name
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        loaded = unreal.EditorAssetLibrary.load_asset(full)
        if not isinstance(loaded, unreal.LevelSequence):
            raise RuntimeError("asset path collision: " + full)
        return loaded, False
    asset = asset_tools.create_asset(
        asset_name=name,
        package_path=package,
        asset_class=unreal.LevelSequence,
        factory=unreal.LevelSequenceFactoryNew(),
    )
    if not asset:
        raise RuntimeError("could not create sequence: " + full)
    return asset, True


def configure_sequence(sequence, frames, fps):
    sequence.set_display_rate(unreal.FrameRate(numerator=fps, denominator=1))
    sequence.set_playback_start(0)
    sequence.set_playback_end(frames)


def build(spec):
    if spec.get("format") != "director_ue_timeline_v1":
        raise RuntimeError("invalid local job format")
    project_id = spec["project_id"]
    episode_id = spec["episode_id"]
    fps = spec["fps"]
    shots = spec["shots"]
    # Python outside Unreal validates each value before writing the manifest.
    if not shots or sum(x["frames"] for x in shots) != spec["total_frames"]:
        raise RuntimeError("invalid local job frame totals")

    prefix = project_id + "_" + episode_id
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    for part in ("/Game/Director", "/Game/Director/Shots",
                 "/Game/Director/Episodes"):
        unreal.EditorAssetLibrary.make_directory(part)
    shot_assets = []
    for shot in shots:
        name = prefix + "_SH" + shot["shot_id"]
        sequence, created = create_if_missing(
            asset_tools, name, "/Game/Director/Shots"
        )
        if not created and sequence.get_playback_end() != shot["frames"]:
            raise RuntimeError("existing shot has different duration: " + name)
        if created:
            configure_sequence(sequence, shot["frames"], fps)
            if not unreal.EditorAssetLibrary.save_loaded_asset(sequence):
                raise RuntimeError("failed to save shot: " + name)
        shot_assets.append(sequence)

    master_name = prefix + "_Master"
    master, created = create_if_missing(
        asset_tools, master_name, "/Game/Director/Episodes"
    )
    if not created:
        # Never modify an existing master without a controlled revision path.
        raise RuntimeError("master sequence already exists; refusing overwrite")

    configure_sequence(master, spec["total_frames"], fps)
    track = master.add_track(unreal.MovieSceneCinematicShotTrack)
    cursor = 0
    for shot, shot_sequence in zip(shots, shot_assets):
        section = track.add_section()
        section.set_sequence(shot_sequence)
        section.set_range(cursor, cursor + shot["frames"])
        cursor += shot["frames"]
    if not unreal.EditorAssetLibrary.save_loaded_asset(master):
        raise RuntimeError("failed to save episode master sequence")
    return {
        "ok": True,
        "master": "/Game/Director/Episodes/" + master_name,
        "shot_count": len(shots),
        "total_frames": cursor,
        "fps": fps,
        "render_ready": False,
        "note": "Timing-only Sequencer; actors/cameras/audio not bound",
    }


def main():
    result_path = Path(os.environ["DIRECTOR_UE_RESULT_FILE"])
    try:
        spec_path = Path(os.environ["DIRECTOR_UE_SPEC_FILE"])
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        result = build(spec)
    except Exception as exc:
        result = {
            "ok": False,
            "reason": str(exc)[:400],
            "traceback": traceback.format_exc(limit=5)[-2000:],
        }
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not result["ok"]:
        # Not all commandlets propagate Python exceptions to process exit code;
        # the worker checks the structured result file independently.
        unreal.log_error("Director UE timeline build failed: " + result["reason"])
    else:
        unreal.log("Director UE timeline build completed")


main()
