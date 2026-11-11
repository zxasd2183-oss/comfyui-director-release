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
PRIVATE_CAMERA_ROOT = "/Game/Director/V071/ShotBindings"
PROOF_SHOTS = ("01", "13", "26", "31")
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
# MRQ is 720x1280, but CineCamera defaults to a 16:9 sensor. With
# bConstrainAspectRatio enabled that renders a 405px-high centre strip and
# massive black bars. Use a REAL 9:16 sensor and disable extra plate crop
# on four cloned-stage cameras only; original 31 V03 shots stay immutable.
PORTRAIT_SENSOR = (13.5, 24.0)
PORTRAIT_CAMERA_SHOTS = {
    "01": ((-480.0, -335.0, 235.0), (140.0, -45.0, 115.0), 20.0),
    "13": (CAMERA13_PREVIEW, CAMERA13_FOCUS, 27.0),
    "26": ((-250.0, 80.0, 230.0), (425.0, 225.0, 145.0), 32.0),
    "31": ((-735.0, 250.0, 235.0), (-245.0, 380.0, 103.0), 28.0),
}
assert set(PORTRAIT_CAMERA_SHOTS) == set(PROOF_SHOTS)


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


def configure_private_portrait_cameras(actors):
    """Physically reframe only four cloned-map cameras for vertical MRQ.

    Verify every read-back before saving, fail closed rather than produce a
    render with stale 16:9 sensor black letterboxes or wrong camera actors.
    """
    receipts = {}
    used = set()
    for shot in PROOF_SHOTS:
        location, focus, focal_mm = PORTRAIT_CAMERA_SHOTS[shot]
        matches = [a for a in actors if a.get_actor_label() == "V03_CAM_SH" + shot]
        if len(matches) != 1 or id(matches[0]) in used:
            raise RuntimeError("portrait_camera_missing_or_duplicate_" + shot)
        camera = matches[0]
        used.add(id(camera))
        component = camera.get_component_by_class(unreal.CineCameraComponent)
        if not component:
            raise RuntimeError("portrait_camera_component_missing_" + shot)
        where = unreal.Vector(*location)
        target = unreal.Vector(*focus)
        rotation = unreal.MathLibrary.find_look_at_rotation(where, target)
        camera.set_actor_location_and_rotation(where, rotation, False, True)
        if any(abs(a - b) > 1.0 for a, b in zip(_coords(camera.get_actor_location()), location)):
            raise RuntimeError("portrait_camera_pose_not_applied_" + shot)
        component.set_editor_property("filmback", unreal.CameraFilmbackSettings(
            sensor_width=PORTRAIT_SENSOR[0], sensor_height=PORTRAIT_SENSOR[1]
        ))
        component.set_editor_property("crop_settings", unreal.PlateCropSettings(
            aspect_ratio=0.0
        ))
        component.set_editor_property("constrain_aspect_ratio", True)
        component.set_editor_property("current_focal_length", focal_mm)
        filmback = component.get_editor_property("filmback")
        crop = component.get_editor_property("crop_settings")
        if (abs(float(filmback.sensor_width) - PORTRAIT_SENSOR[0]) > 0.01 or
                abs(float(filmback.sensor_height) - PORTRAIT_SENSOR[1]) > 0.01 or
                abs(float(crop.aspect_ratio)) > 0.001 or
                component.get_editor_property("constrain_aspect_ratio") is not True or
                abs(float(component.get_editor_property("current_focal_length")) - focal_mm) > 0.1):
            raise RuntimeError("portrait_camera_settings_not_applied_" + shot)
        receipts[shot] = {
            "location": list(location),
            "look_at": list(focus),
            "focal_mm": focal_mm,
            "sensor_mm": list(PORTRAIT_SENSOR),
            "crop_aspect_ratio": 0.0,
            "constrain_aspect_ratio": True,
        }
    if set(receipts) != set(PROOF_SHOTS):
        raise RuntimeError("portrait_preview_camera_count_invalid")
    return receipts


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
    portrait_cameras = configure_private_portrait_cameras(actors)
    # Saving the current level persists ONLY the newly created map.
    if not editor.save_current_level():
        raise RuntimeError("exposure_stage_save_failed")
    return stage, changed, camera13, portrait_cameras


def create_private_bound_sequences(job_id, actors):
    """Bind a NEW camera-cut sequence to each actor in the CLONED level.

    Original V03 possessable bindings refer to actors from another level.
    Reusing them against a new map can silently fall back to a default
    spectator camera. These four job-scoped sequences bind their own
    possessables to the actual preview-map CineCameraActors.
    """
    directory = PRIVATE_CAMERA_ROOT + "/" + job_id
    if unreal.EditorAssetLibrary.does_directory_exist(directory):
        raise RuntimeError("preview_private_sequences_collision")
    if not unreal.EditorAssetLibrary.make_directory(directory):
        raise RuntimeError("preview_private_sequence_directory_failed")
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    result = {}
    used_actors = set()
    for shot in PROOF_SHOTS:
        label = "V03_CAM_SH" + shot
        matching = [a for a in actors if a.get_actor_label() == label]
        if len(matching) != 1:
            raise RuntimeError("preview_camera_missing_or_duplicate_" + shot)
        camera = matching[0]
        if not camera.get_component_by_class(unreal.CineCameraComponent):
            raise RuntimeError("preview_camera_component_missing_" + shot)
        if id(camera) in used_actors:
            raise RuntimeError("preview_camera_actor_reused_" + shot)
        used_actors.add(id(camera))
        name = "WaitingOffice_EP01_SH" + shot + "_V03"
        path = directory + "/" + name
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            raise RuntimeError("preview_private_sequence_collision_" + shot)
        sequence = tools.create_asset(
            asset_name=name, package_path=directory,
            asset_class=unreal.LevelSequence,
            factory=unreal.LevelSequenceFactoryNew()
        )
        if not sequence:
            raise RuntimeError("preview_sequence_creation_failed_" + shot)
        sequence.set_display_rate(unreal.FrameRate(numerator=24, denominator=1))
        sequence.set_playback_start(0)
        sequence.set_playback_end(3)
        binding = unreal.MovieSceneSequenceExtensions.add_possessable(
            sequence, camera
        )
        if not binding:
            raise RuntimeError("preview_camera_possessable_failed_" + shot)
        track = sequence.add_track(unreal.MovieSceneCameraCutTrack)
        section = track.add_section()
        section.set_range(0, 3)
        binding_id = unreal.MovieSceneSequenceExtensions.get_binding_id(
            sequence, binding
        )
        if not binding_id:
            raise RuntimeError("preview_camera_binding_id_missing_" + shot)
        section.set_camera_binding_id(binding_id)
        if not unreal.EditorAssetLibrary.save_loaded_asset(sequence):
            raise RuntimeError("preview_sequence_save_failed_" + shot)
        result[shot] = path + "." + name
    if set(result) != set(PROOF_SHOTS):
        raise RuntimeError("preview_bound_sequence_count_mismatch")
    return result


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
        map_path, light_levels, camera13, portrait_cameras = create_private_exposure_stage(job_id)
        # Only after cloned map has been saved, create NEW cut tracks pointing
        # to the actor instances that live in the cloned map.
        preview_actors = unreal.get_editor_subsystem(
            unreal.EditorActorSubsystem
        ).get_all_level_actors()
        bound_sequences = create_private_bound_sequences(job_id, preview_actors)
        result = {"ok":True, "preset":asset_path + "." + asset_name,
                  "width":720,"height":1280,"frames_per_shot":1,
                  "stage_map":map_path, "source_map":V03_SOURCE_STAGE,
                  "light_intensities":light_levels,
                  "camera13_reframe":camera13,
                  "bound_preview_sequences":bound_sequences,
                  "portrait_preview_cameras":portrait_cameras}
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
