"""Create a fixed low-cost PNG preview MRQ preset in Unreal Editor 5.8.

Executed only as a known commandlet from Director UE Worker. Asset paths and
render output directory are derived from the random server-owned job ID.
The script never renders by itself and never edits V02/V03 story assets.
"""
from __future__ import annotations

import json
import os
import re
import traceback
from pathlib import Path

import unreal

ROOT = "/Game/Director/V04"
PRESET_DIR = ROOT + "/Presets"
V03_SOURCE_STAGE = "/Game/Director/V03/Maps/WaitingOffice_EP01_Stage"
PREVIEW_MAP_DIR = "/Game/Director/V051/Maps"
LIGHT_TARGETS = {
    "V03_Key_Light": (18000.0, 800.0),
    "V03_Fill_Light": (9000.0, 400.0),
}
# The original entrance shot 13 was accidentally positioned only ~216 cm
# from the Zero stand-in. Reframe ONLY the cloned stage's SH13 camera.
CAMERA13_LABEL = "V03_CAM_SH13"
CAMERA13_ORIGINAL = (-420.0, 345.0, 225.0)
CAMERA13_PREVIEW = (-860.0, 345.0, 225.0)
CAMERA13_FOCUS = (-245.0, 380.0, 103.0)


def _coords(vector):
    return (float(vector.x), float(vector.y), float(vector.z))


def fix_private_sh13_camera(actors):
    matching = [a for a in actors if a.get_actor_label() == CAMERA13_LABEL]
    if len(matching) != 1:
        raise RuntimeError("exposure_camera13_missing_or_duplicated")
    camera = matching[0]
    if not camera.get_component_by_class(unreal.CineCameraComponent):
        raise RuntimeError("exposure_camera13_component_missing")
    original = _coords(camera.get_actor_location())
    if any(abs(actual - expected) > 1.0 for actual, expected in
           zip(original, CAMERA13_ORIGINAL)):
        raise RuntimeError("exposure_camera13_source_pose_drift")
    destination = unreal.Vector(*CAMERA13_PREVIEW)
    focus = unreal.Vector(*CAMERA13_FOCUS)
    rotation = unreal.MathLibrary.find_look_at_rotation(destination, focus)
    camera.set_actor_location_and_rotation(destination, rotation, False, True)
    final = _coords(camera.get_actor_location())
    if any(abs(actual - expected) > 1.0 for actual, expected in
           zip(final, CAMERA13_PREVIEW)):
        raise RuntimeError("exposure_camera13_write_failed")
    return {"label": CAMERA13_LABEL, "original": list(original),
            "preview": list(final), "look_at": list(CAMERA13_FOCUS)}


def create_private_exposure_stage(job_id):
    """Copy the original V03 map, then change only the two named point lights.

    UE 5.8 LevelEditorSubsystem.new_level_from_template saves a *new*
    map. Original stage, 31 camera actors, and sequences remain untouched.
    """
    asset = "WO_EP01_ExposurePreview_" + job_id
    stage = PREVIEW_MAP_DIR + "/" + asset
    # EditorAssetLibrary.does_asset_exist is not reliable for LEVEL assets.
    # Derive both .umap paths from the trusted job output, never caller input.
    project_root = Path(os.environ["DIRECTOR_UE_PREVIEW_OUTPUT"]).resolve().parents[3]
    original_file = project_root / "Content" / "Director" / "V03" / "Maps" / "WaitingOffice_EP01_Stage.umap"
    preview_file = project_root / "Content" / "Director" / "V051" / "Maps" / (asset + ".umap")
    if original_file.is_symlink() or not original_file.is_file():
        raise RuntimeError("v03_source_map_missing")
    if preview_file.is_symlink() or preview_file.exists():
        raise RuntimeError("exposure_stage_collision")
    if (not unreal.EditorAssetLibrary.does_directory_exist(PREVIEW_MAP_DIR)
            and not unreal.EditorAssetLibrary.make_directory(PREVIEW_MAP_DIR)):
        raise RuntimeError("exposure_stage_directory_failed")
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not editor or not editor.new_level_from_template(stage, V03_SOURCE_STAGE):
        raise RuntimeError("exposure_stage_clone_failed")
    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = actor_subsystem.get_all_level_actors()
    changed = {}
    for label, (expected, target) in LIGHT_TARGETS.items():
        matching = [a for a in actors if a.get_actor_label() == label]
        if len(matching) != 1:
            raise RuntimeError("exposure_light_label_mismatch_" + label)
        component = matching[0].get_component_by_class(unreal.PointLightComponent)
        if not component:
            raise RuntimeError("exposure_light_component_missing_" + label)
        previous = float(component.get_editor_property("intensity"))
        if abs(previous - expected) > 0.5:
            raise RuntimeError("exposure_source_light_drift_" + label)
        component.set_editor_property("intensity", target)
        measured = float(component.get_editor_property("intensity"))
        if abs(measured - target) > 0.5:
            raise RuntimeError("exposure_light_write_failed_" + label)
        changed[label] = measured
    camera13 = fix_private_sh13_camera(actors)
    # Saving the current level persists ONLY the newly created map.
    if not editor.save_current_level():
        raise RuntimeError("exposure_stage_save_failed")
    return stage, changed, camera13


def main():
    result_file = Path(os.environ["DIRECTOR_UE_RESULT_FILE"])
    try:
        job_id = os.environ["DIRECTOR_UE_JOB_ID"]
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise RuntimeError("invalid_job_id")
        output = Path(os.environ["DIRECTOR_UE_PREVIEW_OUTPUT"]).resolve()
        # Both values come from the trusted Python worker, not from HTTP callers.
        if not output.is_dir() or output.name != "Previews" or output.parent.name != job_id:
            raise RuntimeError("invalid_preview_output_directory")
        for folder in (ROOT, PRESET_DIR):
            unreal.EditorAssetLibrary.make_directory(folder)
        asset_name = "WO_EP01_PrevisPNG_" + job_id
        asset_path = PRESET_DIR + "/" + asset_name
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            raise RuntimeError("preview_preset_collision")
        factory = unreal.MoviePipelinePrimaryConfigFactory()
        config = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            asset_name=asset_name,
            package_path=PRESET_DIR,
            asset_class=unreal.MoviePipelinePrimaryConfig,
            factory=factory,
        )
        if not config:
            raise RuntimeError("movie_pipeline_config_creation_failed")
        config.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
        config.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
        setting = config.find_or_add_setting_by_class(
            unreal.MoviePipelineOutputSetting
        )
        setting.set_editor_property(
            "output_directory", unreal.DirectoryPath(str(output))
        )
        setting.set_editor_property("output_resolution", unreal.IntPoint(720,1280))
        setting.set_editor_property(
            "file_name_format", "{sequence_name}_V04_{frame_number}"
        )
        setting.set_editor_property("use_custom_playback_range", True)
        setting.set_editor_property("custom_start_frame", 0)
        setting.set_editor_property("custom_end_frame", 1)
        setting.set_editor_property("override_existing_output", False)
        if not unreal.EditorAssetLibrary.save_loaded_asset(config):
            raise RuntimeError("preview_preset_save_failed")
        # Source V03.umap remains immutable; never apply light changes in place.
        map_path, light_levels, camera13 = create_private_exposure_stage(job_id)
        result = {"ok":True, "preset":asset_path + "." + asset_name,
                  "width":720,"height":1280,"frames_per_shot":1,
                  "stage_map":map_path, "source_map":V03_SOURCE_STAGE,
                  "light_intensities":light_levels,
                  "camera13_reframe":camera13}
    except Exception as exc:
        result = {"ok":False, "reason":str(exc)[:400],
                  "traceback":traceback.format_exc(limit=5)[-2000:]}
    result_file.write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    if result["ok"]:
        unreal.log("Director V04 preview preset created")
    else:
        unreal.log_error("Director V04 preview preset failed: " + result["reason"])


main()
