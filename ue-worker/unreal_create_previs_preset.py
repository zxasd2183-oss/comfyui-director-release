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



# V1.1 genuine image review: clone ONLY the known V1.0 authored cast World,
# create job-isolated sequences with bound CineCameraActors and MRQ PNG presets.
# The source remains unchanged, and these are NOT AI-generated concept images.
V11_CAST_SOURCE_JOB = "f32dea96d7a94990b3eb274d1cef3de3"
V11_CAST_SOURCE = ("/Game/Director/Candidates/EP01/CastBuilds/J"
                   + V11_CAST_SOURCE_JOB + "/Maps/EP01_Five_Cast_Review")
V11_VIEWS = ("LINEUP", "GPT", "GEM", "DS", "CLA", "ZERO")
V11_MAIN_CAST = ("GPT", "GEM", "DS", "CLA", "ZERO")
V11_CAMERA_POSES = {
    # Portrait cameras face the front (+X) of V1.0 actor components.
    # A 13.5 x 24 mm filmback prevents 16:9 letterbox bars in 9:16 renders.
    # Fixed review lens: figures fit vertically and other characters stay
    # OUTSIDE single-actor 9:16 crops. Prior 20mm lens exposed neighbors.
    "LINEUP": ((930, 0, 125), (0, 0, 112), 40.0, (36.0, 20.25)),
    "GPT": ((480, -330, 113), (0, -330, 113), 50.0, (13.5, 24.0)),
    "GEM": ((480, -165, 113), (0, -165, 113), 50.0, (13.5, 24.0)),
    "DS": ((480, 0, 113), (0, 0, 113), 50.0, (13.5, 24.0)),
    "CLA": ((480, 165, 113), (0, 165, 113), 50.0, (13.5, 24.0)),
    "ZERO": ((480, 330, 113), (0, 330, 113), 50.0, (13.5, 24.0)),
}



def apply_v120_cast_review_look(actors, actor_by_short):
    """Fix exposure and visibility in ONLY a clone of the authored V1.0 World.

    No master Blueprint, source actor, or production Studio asset is modified.
    Changes are true Unreal scene/component overrides that persist in the
    job-owned review map and affect actual MRQ output.
    """
    # Original five female figures are deliberately static design maquettes.
    # The V1.0 head is an ellipsoid of 55cm X radius. Iris X=25cm was INSIDE
    # the face and invisible; use frontal (+X) component placement.
    iris_names=(
        "Right_Eye_Iris","Left_Eye_Iris",
        "Right_Eye_Highlight","Left_Eye_Highlight",
        "Right_Brow","Left_Brow",
        "Nose","Mouth_Center",
    )
    override_count=0
    for short,actor in actor_by_short.items():
        cmap={}
        for comp in actor.get_components_by_class(unreal.StaticMeshComponent):
            raw=str(comp.get_name())
            clean=raw.split("_GEN_VARIABLE")[0]
            cmap[clean]=comp
        missing=[name for name in iris_names if name not in cmap]
        if missing:
            raise RuntimeError("cast_review_face_components_missing_"+short)
        for name in iris_names:
            comp=cmap[name]
            old=comp.relative_location
            x=(62 if "Highlight" in name else 57 if "Iris" in name
               else 58 if "Brow" in name else 60 if name=="Nose" else 58)
            comp.set_relative_location(
                unreal.Vector(float(x),float(old.y),float(old.z)),
                False,False)
            override_count+=1
        # Hairstyles already distinguish all five characters in V1.0.
        # Reveal previously half-buried asymmetric fringes on the forehead.
        if short=="GPT" and "Hair_SidePart_Fringe" in cmap:
            cmap["Hair_SidePart_Fringe"].set_relative_location(
                unreal.Vector(34,14,192),False,False)
            override_count+=1
        if short=="GEM":
            for name in ("Hair_Layer_00","Hair_Layer_01",
                         "Hair_Layer_02","Hair_Layer_03"):
                if name not in cmap:
                    raise RuntimeError("cast_review_gem_layer_missing")
                old=cmap[name].relative_location
                cmap[name].set_relative_location(
                    unreal.Vector(float(old.x+22),float(old.y),
                                  float(old.z)),False,False)
                override_count+=1
        if short=="DS":
            for idx in range(7):
                key="Hair_Braid_%02d"%idx
                if key not in cmap:
                    raise RuntimeError("cast_review_braid_missing")
                # Bring the long blue braid forward to be visible on shoulder.
                cmap[key].set_relative_location(
                    unreal.Vector(16,-35,float(147-idx*12)),
                    False,False)
                override_count+=1
        if short=="ZERO":
            if "Right_Wrist_Red_Thread" not in cmap:
                raise RuntimeError("cast_review_zero_red_thread_missing")
            wrist=cmap["Right_Wrist_Red_Thread"].relative_location
            if float(wrist.y)>=0:
                raise RuntimeError("cast_review_zero_wrist_not_right")
    if override_count<52:
        raise RuntimeError("cast_review_face_visibility_not_applied")

    # Separate trustworthy assets from studio lighting. Neither path can
    # escape the locked V1.0 actor build namespace.
    materials=("/Game/Director/Candidates/EP01/CastBuilds/J"+
               V11_CAST_SOURCE_JOB+"/Materials/M_")
    mat_floor=unreal.EditorAssetLibrary.load_asset(materials+"Charcoal")
    mat_wall=unreal.EditorAssetLibrary.load_asset(materials+"Parchment")
    mesh_cube=unreal.EditorAssetLibrary.load_asset(
        "/Engine/BasicShapes/Cube.Cube")
    if not mat_floor or not mat_wall or not mesh_cube:
        raise RuntimeError("cast_review_stage_assets_missing")
    levels=actors.get_all_level_actors()
    floors=[actor for actor in levels
            if actor.get_actor_label()=="WO_CANDIDATE_ReviewFloor"]
    if len(floors)!=1:
        raise RuntimeError("cast_review_floor_missing")
    floor_comp=floors[0].get_component_by_class(unreal.StaticMeshComponent)
    if not floor_comp:
        raise RuntimeError("cast_review_floor_component_missing")
    floor_comp.set_material(0,mat_floor)

    # Real neutral backdrop; the previous camera saw infinite black outside
    # the floor, triggering extreme brightness adaptation with 5k fills.
    wall=actors.spawn_actor_from_class(
        unreal.StaticMeshActor,unreal.Vector(-170,0,180),
        unreal.Rotator(0,0,0))
    if not wall:
        raise RuntimeError("cast_review_backdrop_spawn_failed")
    wall.set_actor_label("WO_V120_NeutralBackdrop")
    wall_comp=wall.get_component_by_class(unreal.StaticMeshComponent)
    if not wall_comp or not wall_comp.set_static_mesh(mesh_cube):
        raise RuntimeError("cast_review_backdrop_mesh_missing")
    wall_comp.set_material(0,mat_wall)
    wall.set_actor_scale3d(unreal.Vector(.16,10.0,5.0))

    original=[actor for actor in levels
              if actor.get_actor_label()=="WO_CANDIDATE_ReviewLight"]
    if len(original)!=1:
        raise RuntimeError("cast_review_source_light_missing")
    light=original[0].get_component_by_class(unreal.PointLightComponent)
    if not light:
        raise RuntimeError("cast_review_source_light_component_missing")
    light.set_editor_property("intensity",350.0)

    volume=actors.spawn_actor_from_class(
        unreal.PostProcessVolume,unreal.Vector(0,0,0),
        unreal.Rotator(0,0,0))
    if not volume:
        raise RuntimeError("cast_review_postprocess_spawn_failed")
    volume.set_actor_label("WO_V120_FixedExposure")
    volume.set_editor_property("unbound",True)
    volume.set_editor_property("priority",100.0)
    volume.set_editor_property("blend_weight",1.0)
    settings=volume.get_editor_property("settings")
    settings.set_editor_property("auto_exposure_method",
                                 unreal.AutoExposureMethod.AEM_MANUAL)
    settings.set_editor_property("override_auto_exposure_method",True)
    settings.set_editor_property(
        "auto_exposure_apply_physical_camera_exposure",False)
    settings.set_editor_property(
        "override_auto_exposure_apply_physical_camera_exposure",True)
    settings.set_editor_property("auto_exposure_bias",-1.5)
    settings.set_editor_property("override_auto_exposure_bias",True)
    settings.set_editor_property("bloom_intensity",0.0)
    settings.set_editor_property("override_bloom_intensity",True)
    volume.set_editor_property("settings",settings)
    return {"face_component_overrides":override_count,
            "exposure_method":"manual","exposure_bias":-1.5,
            "bloom_intensity":0.0,
            "floor_material":"Charcoal","backdrop_material":"Parchment",
            "v120_source_master_unchanged":True}

def cast_review_main():
    """Make 6 deterministic MRQ single-frame visual verification views."""
    result_file = Path(os.environ["DIRECTOR_UE_RESULT_FILE"])
    try:
        ident = os.environ["DIRECTOR_UE_JOB_ID"]
        if not re.fullmatch(r"[a-f0-9]{32}", ident):
            raise RuntimeError("cast_review_job_id_invalid")
        if os.environ.get("DIRECTOR_UE_REVIEW_MODE") != "cast_v11":
            raise RuntimeError("cast_review_mode_not_allowed")
        output = Path(os.environ["DIRECTOR_UE_PREVIEW_OUTPUT"]).resolve()
        project = output.parents[3]
        if (output.name != "Previews" or output.parent.name != ident
                or output.parent.parent.name != "V11"
                or output.parent.parent.parent.name != "Outputs"):
            raise RuntimeError("cast_review_output_location_invalid")
        source_file = (
            project / "Content" / "Director" / "Candidates" / "EP01"
            / "CastBuilds" / ("J" + V11_CAST_SOURCE_JOB)
            / "Maps" / "EP01_Five_Cast_Review.umap"
        )
        if source_file.is_symlink() or not source_file.is_file():
            raise RuntimeError("cast_v100_review_world_missing")
        prefix = "/Game/Director/Candidates/EP01/ReviewRenders/J" + ident
        preview = prefix + "/Maps/WO_EP01_CastReview"
        dest_file = (
            project / "Content" / "Director" / "Candidates" / "EP01"
            / "ReviewRenders" / ("J" + ident) / "Maps"
            / "WO_EP01_CastReview.umap"
        )
        if dest_file.exists() or dest_file.is_symlink():
            raise RuntimeError("cast_review_map_collision")
        for folder in (prefix,prefix+"/Maps",prefix+"/Shots",prefix+"/Presets"):
            if unreal.EditorAssetLibrary.does_directory_exist(folder):
                raise RuntimeError("cast_review_directory_collision")
            if not unreal.EditorAssetLibrary.make_directory(folder):
                raise RuntimeError("cast_review_directory_failure")
        editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if not editor.new_level_from_template(preview,V11_CAST_SOURCE):
            raise RuntimeError("cast_review_world_clone_failed")
        actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        existing=actors.get_all_level_actors()
        known={}
        cast_actors={}
        for index,short in enumerate(V11_MAIN_CAST):
            label="WO_CANDIDATE_CHAR_"+short
            matched=[actor for actor in existing
                     if actor.get_actor_label()==label]
            if len(matched)!=1:
                raise RuntimeError("cast_review_actor_missing_"+short)
            loc=matched[0].get_actor_location()
            where=(float(loc.x),float(loc.y),float(loc.z))
            if (abs(where[0])>1 or
                    abs(where[1]-(index-2)*165)>1 or
                    abs(where[2])>1):
                raise RuntimeError("cast_actor_position_mismatch_"+short)
            known[short]=label
            cast_actors[short]=matched[0]

        look=apply_v120_cast_review_look(actors,cast_actors)
        # Low-power neutral soft front fill instead of two 5000-unit lights.
        # Dedicated uniform front fill: source floor, static meshes and lamp
        # remain untouched, only cloned review World receives extra lights.
        for name,y in (("ReviewFrontL",-360),("ReviewFrontR",360)):
            light=actors.spawn_actor_from_class(
                unreal.PointLight,unreal.Vector(360,y,330),
                unreal.Rotator(0,0,0))
            if not light:
                raise RuntimeError("cast_review_fill_light_missing")
            light.set_actor_label("WO_V11_"+name)
            comp=light.get_component_by_class(unreal.PointLightComponent)
            comp.set_editor_property("intensity",550.0)
            comp.set_editor_property("attenuation_radius",2000.0)

        cameras={}
        for view in V11_VIEWS:
            location,target,focal,sensor=V11_CAMERA_POSES[view]
            position=unreal.Vector(*location)
            camera=actors.spawn_actor_from_class(
                unreal.CineCameraActor,position,
                unreal.MathLibrary.find_look_at_rotation(
                    position,unreal.Vector(*target)))
            if not camera:
                raise RuntimeError("cast_review_camera_spawn_failed_"+view)
            camera.set_actor_label("WO_V11_CAM_"+view)
            comp=camera.get_component_by_class(unreal.CineCameraComponent)
            if not comp:
                raise RuntimeError("cast_review_camera_component_missing_"+view)
            comp.set_editor_property(
                "filmback",unreal.CameraFilmbackSettings(
                    sensor_width=sensor[0],sensor_height=sensor[1]))
            comp.set_editor_property(
                "crop_settings",unreal.PlateCropSettings(aspect_ratio=0.0))
            comp.set_editor_property("constrain_aspect_ratio",True)
            comp.set_editor_property("current_focal_length",focal)
            actual=comp.get_editor_property("filmback")
            if (abs(float(actual.sensor_width)-sensor[0])>.01 or
                    abs(float(actual.sensor_height)-sensor[1])>.01):
                raise RuntimeError("cast_review_filmback_not_applied_"+view)
            cameras[view]=camera
        if not editor.save_current_level():
            raise RuntimeError("cast_review_map_save_failed")

        tools=unreal.AssetToolsHelpers.get_asset_tools()
        sequences={}
        for view in V11_VIEWS:
            name="WO_EP01_CAST_"+view
            package=prefix+"/Shots"
            seq=tools.create_asset(
                asset_name=name,package_path=package,
                asset_class=unreal.LevelSequence,
                factory=unreal.LevelSequenceFactoryNew())
            if not seq:
                raise RuntimeError("cast_review_sequence_failed_"+view)
            seq.set_display_rate(unreal.FrameRate(numerator=24,denominator=1))
            seq.set_playback_start(0)
            seq.set_playback_end(3)
            bound=unreal.MovieSceneSequenceExtensions.add_possessable(
                seq,cameras[view])
            if not bound:
                raise RuntimeError("cast_review_binding_failed_"+view)
            track=seq.add_track(unreal.MovieSceneCameraCutTrack)
            section=track.add_section()
            section.set_range(0,3)
            binding_id=unreal.MovieSceneSequenceExtensions.get_binding_id(
                seq,bound)
            if not binding_id:
                raise RuntimeError("cast_review_camera_id_failed_"+view)
            section.set_camera_binding_id(binding_id)
            if not unreal.EditorAssetLibrary.save_loaded_asset(seq):
                raise RuntimeError("cast_review_sequence_save_failed_"+view)
            sequences[view]=package+"/"+name+"."+name

        presets={}
        for mode,width,height in (("wide",1280,720),("portrait",720,1280)):
            name="WO_EP01_CastPNG_"+mode
            preset=tools.create_asset(
                asset_name=name,package_path=prefix+"/Presets",
                asset_class=unreal.MoviePipelinePrimaryConfig,
                factory=unreal.MoviePipelinePrimaryConfigFactory())
            if not preset:
                raise RuntimeError("cast_review_mrq_config_failed_"+mode)
            preset.find_or_add_setting_by_class(
                unreal.MoviePipelineDeferredPassBase)
            preset.find_or_add_setting_by_class(
                unreal.MoviePipelineImageSequenceOutput_PNG)
            setting=preset.find_or_add_setting_by_class(
                unreal.MoviePipelineOutputSetting)
            setting.set_editor_property(
                "output_directory",unreal.DirectoryPath(str(output)))
            setting.set_editor_property(
                "output_resolution",unreal.IntPoint(width,height))
            setting.set_editor_property(
                "file_name_format","{sequence_name}_V11_{frame_number}")
            setting.set_editor_property("use_custom_playback_range",True)
            setting.set_editor_property("custom_start_frame",0)
            setting.set_editor_property("custom_end_frame",1)
            setting.set_editor_property("override_existing_output",False)
            if not unreal.EditorAssetLibrary.save_loaded_asset(preset):
                raise RuntimeError("cast_review_mrq_save_failed_"+mode)
            presets[mode]=prefix+"/Presets/"+name+"."+name
        result={
            "ok":True,"source_world":V11_CAST_SOURCE,
            "review_world":preview,"cast":known,
            "view_sequences":sequences,"mrq_presets":presets,
            "views":list(V11_VIEWS),"frames_per_view":1,
            "source_world_unchanged":True,
            "review_look":look,
        }
    except Exception as exc:
        result={"ok":False,"reason":str(exc)[:400],
                "traceback":traceback.format_exc(limit=5)[-1800:]}
    result_file.write_text(json.dumps(result,ensure_ascii=False,indent=2),
                           encoding="utf-8")
    if result["ok"]:
        unreal.log("V11 real Unreal cast review map and camera-cut sequences saved")
    else:
        unreal.log_error("V11 cast-review failed: "+result["reason"])




def hero_metahuman_seed_main():
    """Create one *real native* MetaHumanCharacter candidate (not a rig).

    This code only executes through the fixed signed Worker job under the
    isolated DirectorHeroGPT project. No user-provided paths or meshes.
    It never requests cloud authentication, textures, rigs or assembly.
    """
    result_file=Path(os.environ["DIRECTOR_UE_RESULT_FILE"])
    try:
        job_id=os.environ.get("DIRECTOR_UE_JOB_ID","")
        if not re.fullmatch(r"[a-f0-9]{32}",job_id):
            raise RuntimeError("hero_invalid_job_id")
        if os.environ.get("DIRECTOR_UE_REVIEW_MODE")!="hero_seed_v130":
            raise RuntimeError("hero_invalid_execution_mode")
        package="/Game/Director/Candidates/EP01/HeroBuilds/J"+job_id
        asset_name="MHC_CHAR_GPT"
        target=package+"/"+asset_name
        if unreal.EditorAssetLibrary.does_directory_exist(package):
            raise RuntimeError("hero_candidate_folder_collision")
        if unreal.EditorAssetLibrary.does_asset_exist(target):
            raise RuntimeError("hero_candidate_asset_collision")
        required=("MetaHumanCharacter","MetaHumanCharacterFactoryNew")
        for key in required:
            if not hasattr(unreal,key):
                raise RuntimeError("hero_mhc_plugin_api_missing_"+key)
        if not unreal.EditorAssetLibrary.make_directory(package):
            raise RuntimeError("hero_candidate_directory_failed")
        factory=unreal.MetaHumanCharacterFactoryNew()
        factory.set_editor_property("edit_after_new",False)
        asset=unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            asset_name=asset_name,package_path=package,
            asset_class=unreal.MetaHumanCharacter,factory=factory)
        if not asset:
            raise RuntimeError("hero_mhc_asset_creation_failed")
        if asset.get_class().get_name()!="MetaHumanCharacter":
            raise RuntimeError("hero_mhc_asset_wrong_type")
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset):
            raise RuntimeError("hero_mhc_asset_save_failed")
        if not unreal.EditorAssetLibrary.does_asset_exist(target):
            raise RuntimeError("hero_mhc_asset_not_persisted")
        reloaded=unreal.EditorAssetLibrary.load_asset(target)
        if not reloaded or reloaded.get_class().get_name()!="MetaHumanCharacter":
            raise RuntimeError("hero_mhc_reload_failed")
        result={"ok":True,"kind":"real_native_metahuman_character_seed_v130",
                "asset_path":target,"asset_class":"MetaHumanCharacter",
                "project":"DirectorHeroGPT",
                "independent_ep01_source_untouched":True,
                "rigging_done":False,"textures_downloaded":False,
                "groom_applied":False,"wardrobe_applied":False,
                "character_master_approved":False,
                "cinematic_character_ready":False}
    except Exception as exc:
        result={"ok":False,"reason":str(exc)[:240],
                "traceback":traceback.format_exc(limit=5)[-1200:]}
    result_file.write_text(json.dumps(result,ensure_ascii=False,indent=2),
                           encoding="utf-8")
    if result["ok"]:
        unreal.log("EP01 GPT real MetaHuman Character candidate saved")
    else:
        unreal.log_error("EP01 GPT MetaHuman seed creation failed: "+result["reason"])


def hero_metahuman_runtime_audit_main():
    """Read-only test of one verified GPT MetaHuman in UE 5.8."""
    result_file=Path(os.environ["DIRECTOR_UE_RESULT_FILE"])
    try:
        ident=os.environ.get("DIRECTOR_UE_JOB_ID","")
        if (not re.fullmatch(r"[a-f0-9]{32}",ident) or
            os.environ.get("DIRECTOR_UE_REVIEW_MODE")!="hero_audit_v140"):
            raise RuntimeError("hero_audit_untrusted_job")
        seed="d5253c965631447684e49613533e85ad"
        asset_path=("/Game/Director/Candidates/EP01/HeroBuilds/J"+
                    seed+"/MHC_CHAR_GPT")
        asset=unreal.EditorAssetLibrary.load_asset(asset_path)
        if not asset or asset.get_class().get_name()!="MetaHumanCharacter":
            raise RuntimeError("hero_audit_native_metahuman_missing")
        editor_exists=hasattr(unreal,"MetaHumanCharacterEditorSubsystem")
        subsystem=(unreal.get_editor_subsystem(
            unreal.MetaHumanCharacterEditorSubsystem)
            if editor_exists else None)
        api={
            "character_editor_subsystem":subsystem is not None,
            "request_auto_rigging":bool(subsystem and hasattr(
                subsystem,"request_auto_rigging")),
            "request_texture_sources":bool(subsystem and hasattr(
                subsystem,"request_texture_sources")),
            "build_meta_human":bool(subsystem and hasattr(
                subsystem,"build_meta_human")),
            "try_add_object_to_edit":bool(subsystem and hasattr(
                subsystem,"try_add_object_to_edit")),
            "commit_eyes_settings":bool(subsystem and hasattr(
                subsystem,"commit_eyes_settings")),
        }
        # Only inspect installed example files, not arbitrary external paths.
        plugin=Path(unreal.Paths.engine_dir()).resolve()/"Plugins"/"MetaHuman"/(
            "MetaHumanCharacter")/"Content"/"Python"/"examples"
        examples={
            "create":(plugin/"example_create_asset.py").is_file(),
            "texture":(plugin/"example_download_textures.py").is_file(),
            "rig":(plugin/"example_auto_rig.py").is_file(),
            "assembly":(plugin/"example_assembly.py").is_file(),
        }
        try:
            highres=asset.get_editor_property("has_high_resolution_textures")
            source_state=("present" if highres is True else "absent"
                          if highres is False else "unknown")
        except Exception:
            source_state="unknown"
        result={
            "ok":True,"asset_path":asset_path,
            "asset_class":asset.get_class().get_name(),
            "capabilities":api,"reference_examples":examples,
            "texture_source_state":source_state,
            "rigged":False,"costly_cloud_requests_executed":False,
            "source_unmodified":True,"character_master_approved":False,
        }
    except Exception as exc:
        result={"ok":False,"reason":str(exc)[:200],
                "traceback":traceback.format_exc(limit=5)[-1100:]}
    result_file.write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    if result["ok"]:
        unreal.log("GPT MetaHuman UE runtime read-only audit completed")
    else:
        unreal.log_error("GPT MetaHuman runtime audit failed "+result["reason"])



def hero_amber_eyes_main():
    """Duplicate source native MetaHuman; configure both iris materials.

    Only the separately reviewed candidate is modified. This is a material
    editing pass, not a claim of an approved likeness, rig, groom or wardrobe.
    """
    output=Path(os.environ["DIRECTOR_UE_RESULT_FILE"])
    try:
        ident=os.environ.get("DIRECTOR_UE_JOB_ID","")
        if (not re.fullmatch(r"[a-f0-9]{32}",ident) or
            os.environ.get("DIRECTOR_UE_REVIEW_MODE")!="hero_eyes_v150"):
            raise RuntimeError("hero_eyes_job_invalid")
        old=("d5253c965631447684e49613533e85ad")
        source=("/Game/Director/Candidates/EP01/HeroBuilds/J"+old+
                "/MHC_CHAR_GPT")
        candidate=("/Game/Director/Candidates/EP01/HeroLooks/J"+ident+
                   "/MHC_CHAR_GPT_AmberV1")
        if unreal.EditorAssetLibrary.does_asset_exist(candidate):
            raise RuntimeError("hero_eyes_candidate_collision")
        if not unreal.EditorAssetLibrary.does_asset_exist(source):
            raise RuntimeError("hero_eyes_source_missing")
        clone=unreal.EditorAssetLibrary.duplicate_asset(source,candidate)
        if not clone or clone.get_class().get_name()!="MetaHumanCharacter":
            raise RuntimeError("hero_eyes_native_clone_failed")
        eyes=clone.get_editor_property("eyes_settings")
        # Linear amber-brown tint applied equally to both existing irises.
        # This is an actual editable MetaHuman material parameter, not pixels.
        tint=unreal.LinearColor(0.85,0.55,0.25,1.0)
        saturation=1.25
        for which in ("eye_left","eye_right"):
            eye=eyes.get_editor_property(which)
            iris=eye.get_editor_property("iris")
            iris.set_editor_property("global_tint",tint)
            iris.set_editor_property("global_saturation",saturation)
            eye.set_editor_property("iris",iris)
            eyes.set_editor_property(which,eye)
        clone.set_editor_property("eyes_settings",eyes)
        if not unreal.EditorAssetLibrary.save_loaded_asset(clone):
            raise RuntimeError("hero_eyes_candidate_save_failed")
        reloaded=unreal.EditorAssetLibrary.load_asset(candidate)
        if not reloaded or reloaded.get_class().get_name()!="MetaHumanCharacter":
            raise RuntimeError("hero_eyes_readback_failed")
        verify=reloaded.get_editor_property("eyes_settings")
        for which in ("eye_left","eye_right"):
            iris=verify.get_editor_property(which).get_editor_property("iris")
            ct=iris.get_editor_property("global_tint")
            got=[float(ct.r),float(ct.g),float(ct.b),float(ct.a)]
            if (any(abs(a-b)>0.002 for a,b in zip(
                got,(0.85,0.55,0.25,1.0))) or
                abs(float(iris.get_editor_property("global_saturation"))-
                    saturation)>0.002):
                raise RuntimeError("hero_eyes_tint_not_persisted_"+which)
        result={"ok":True,"asset_path":candidate,
                "asset_class":"MetaHumanCharacter",
                "eye_tint_linear":[0.85,0.55,0.25,1.0],
                "eye_saturation":1.25,
                "both_eyes_readback_verified":True,
                "original_asset_untouched":True,
                "groom_applied":False,"wardrobe_applied":False,
                "face_rig_created":False,
                "cinematic_character_ready":False,
                "character_master_approved":False}
    except Exception as exc:
        result={"ok":False,"reason":str(exc)[:220],
                "traceback":traceback.format_exc(limit=5)[-1100:]}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),
                      encoding="utf-8")
    if result["ok"]:
        unreal.log("GPT amber eye native MetaHuman candidate saved")
    else:
        unreal.log_error("GPT amber eye candidate failed "+result["reason"])



def hero_face_contour_main():
    """Sculpt a subtle lower-face contour on a NEW native MetaHuman copy.

    Use UE's documented MetaHuman Editor landmark/commit API. This does not
    request cloud data, rig or texture services, nor approve the creative look.
    """
    import math
    output=Path(os.environ["DIRECTOR_UE_RESULT_FILE"])
    result={"ok":False,"reason":"hero_face_not_started"}
    phase="identity"
    diagnostic={"landmark_count":None,"y_span":None,"z_span":None,
                "lower_left":None,"lower_right":None}
    subsystem=None
    clone=None
    registered=False
    try:
        job=os.environ.get("DIRECTOR_UE_JOB_ID","")
        if (os.environ.get("DIRECTOR_UE_REVIEW_MODE")!="hero_face_v170"
                or not re.fullmatch(r"[a-f0-9]{32}",job)):
            raise RuntimeError("invalid_job")
        old="da7a5a59132d4e279f0433f4af1b94ce"
        source=("/Game/Director/Candidates/EP01/HeroLooks/J"+old+
                "/MHC_CHAR_GPT_AmberV1")
        candidate=("/Game/Director/Candidates/EP01/HeroFaces/J"+job+
                   "/MHC_CHAR_GPT_FaceContourV1")
        phase="source"
        if (not unreal.EditorAssetLibrary.does_asset_exist(source)
                or unreal.EditorAssetLibrary.does_asset_exist(candidate)):
            raise RuntimeError("asset_missing_or_collision")
        phase="duplicate"
        clone=unreal.EditorAssetLibrary.duplicate_asset(source,candidate)
        if not clone or clone.get_class().get_name()!="MetaHumanCharacter":
            raise RuntimeError("native_duplicate_failed")
        phase="register"
        subsystem=unreal.get_editor_subsystem(
            unreal.MetaHumanCharacterEditorSubsystem)
        if not subsystem or not subsystem.try_add_object_to_edit(clone):
            raise RuntimeError("metahuman_core_data_or_registration_unavailable")
        registered=True
        phase="get_landmarks"
        landmarks=list(subsystem.get_face_landmarks(clone))
        diagnostic["landmark_count"]=len(landmarks)
        phase="landmark_count"
        if not 20<=len(landmarks)<=1000:
            raise RuntimeError("unexpected_landmark_count")
        phase="landmark_coordinates"
        coords=[]
        for point in landmarks:
            x,y,z=float(point.x),float(point.y),float(point.z)
            if not all(math.isfinite(q) and abs(q)<=1000 for q in (x,y,z)):
                raise RuntimeError("invalid_landmark_coordinate")
            coords.append((x,y,z))
        ys=[item[1] for item in coords]
        zs=sorted(item[2] for item in coords)
        mid_y=(max(ys)+min(ys))/2.0
        half_width=(max(ys)-min(ys))/2.0
        height=zs[-1]-zs[0]
        diagnostic["y_span"]=round(2.0*half_width,3)
        diagnostic["z_span"]=round(height,3)
        phase="landmark_scale"
        if not (0.5<=half_width<=100.0 and 1.0<=height<=150.0):
            raise RuntimeError("face_landmark_scale_unusable")
        z_cut=zs[int(len(zs)*0.38)]
        left=[(i, abs(v[1]-mid_y)) for i,v in enumerate(coords)
              if v[2]<=z_cut and v[1]<mid_y-half_width*0.28]
        right=[(i, abs(v[1]-mid_y)) for i,v in enumerate(coords)
               if v[2]<=z_cut and v[1]>mid_y+half_width*0.28]
        left=sorted(left,key=lambda x:x[1],reverse=True)[:12]
        right=sorted(right,key=lambda x:x[1],reverse=True)[:12]
        diagnostic["lower_left"]=len(left)
        diagnostic["lower_right"]=len(right)
        phase="landmark_jaw_selection"
        if len(left)<3 or len(right)<3:
            raise RuntimeError("jaw_landmarks_not_symmetric")
        selected=sorted([i for i,_ in left+right])
        deltas=[]
        for index in selected:
            side=coords[index][1]-mid_y
            # Max 1 mm/side, gentle 1.5% width reduction in lower face.
            shift=-math.copysign(min(0.10,abs(side)*0.015),side)
            deltas.append(unreal.Vector(0.0,shift,0.0))
        phase="sculpt"
        subsystem.translate_face_landmarks(clone,selected,deltas)
        subsystem.commit_face_state(clone)
        after=list(subsystem.get_face_landmarks(clone))
        if len(after)!=len(landmarks):
            raise RuntimeError("landmark_count_changed")
        changed=sum(
            1 for i in selected
            if abs(float(after[i].y)-coords[i][1])>0.00001
        )
        if changed<2:
            raise RuntimeError("sculpt_not_applied")
        phase="save"
        if not unreal.EditorAssetLibrary.save_loaded_asset(clone):
            raise RuntimeError("candidate_save_failed")
        result={"ok":True,"character_id":"CHAR_GPT","asset_path":candidate,
                "asset_class":"MetaHumanCharacter",
                "face_edit_api":"translate_face_landmarks_commit_face_state",
                "landmark_count":len(landmarks),
                "landmarks_selected":len(selected),
                "live_landmarks_changed":changed,
                "max_lateral_delta_cm":0.10,
                "jaw_style":"subtle_symmetric_lower_face_narrowing_v1",
                "real_ue_sculpt_committed":True,
                "original_asset_untouched":True,
                "cloud_requests_executed":False,
                "rigging_done":False,"high_res_textures_downloaded":False,
                "groom_applied":False,"wardrobe_applied":False,
                "cinematic_character_ready":False,
                "character_master_approved":False,
                "visual_approved":False}
    except Exception as exc:
        # Only an allowlisted phase, an exception CLASS and bounded numeric
        # landmark counts/spans may enter local worker logs. No exception
        # messages, URLs, command lines, tokens, or filesystem paths.
        reason="hero_face_step_failed_"+phase
        result={"ok":False,"reason":reason}
        unreal.log_warning("Director Face Probe phase="+phase+
            " exception="+type(exc).__name__+
            " landmark_count="+str(diagnostic["landmark_count"])+
            " y_span="+str(diagnostic["y_span"])+
            " z_span="+str(diagnostic["z_span"])+
            " lower_left="+str(diagnostic["lower_left"])+
            " lower_right="+str(diagnostic["lower_right"]))
    finally:
        if registered:
            try:
                subsystem.remove_object_to_edit(clone)
            except Exception:
                result={"ok":False,"reason":"hero_face_unregister_failed"}
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),
                          encoding="utf-8")
    if result["ok"]:
        unreal.log("GPT MetaHuman native lower-face contour candidate committed")
    else:
        # Script failure is reported via a signed-worker receipt; do not
        # turn expected preflight failures into opaque commandlet exit codes.
        unreal.log_warning("GPT face sculpt blocked "+result["reason"])


if os.environ.get("DIRECTOR_UE_REVIEW_MODE") == "hero_face_v170":
    hero_face_contour_main()
elif os.environ.get("DIRECTOR_UE_REVIEW_MODE") == "hero_eyes_v150":
    hero_amber_eyes_main()
elif os.environ.get("DIRECTOR_UE_REVIEW_MODE") == "hero_audit_v140":
    hero_metahuman_runtime_audit_main()
elif os.environ.get("DIRECTOR_UE_REVIEW_MODE") == "hero_seed_v130":
    hero_metahuman_seed_main()
elif os.environ.get("DIRECTOR_UE_REVIEW_MODE") == "cast_v11":
    cast_review_main()
else:
    main()
