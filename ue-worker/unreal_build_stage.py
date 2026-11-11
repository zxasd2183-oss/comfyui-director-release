"""Original blocking-stage + 31 cinematic cameras for WaitingOffice EP01.

Runs only inside UE 5.8 Python commandlet under the dedicated non-admin worker.
Does not edit V0.2 sequences or import unapproved MetaHuman assets. Every V0.3
asset is written into a separate /Game/Director/V03 namespace and never
overwritten. The created humans are clearly labeled geometry stand-ins.
"""
from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

import unreal

V03 = "/Game/Director/V03"
STAGE_MAP = V03 + "/Maps/WaitingOffice_EP01_Stage"
SHOT_FOLDER = V03 + "/Shots"
EPISODE_FOLDER = V03 + "/Episodes"
MASTER_PATH = EPISODE_FOLDER + "/WaitingOffice_EP01_Master_V03"
STANDIN_LABELS = ("Gemini", "DeepSeek", "GPT", "Claude", "Zero")
# Relative to the hall table; never claim these are final acting/camera blocking.
STANDINS = {
    "Gemini": (150, -225, 103),
    "DeepSeek": (120, -105, 103),
    "GPT": (105, 30, 103),
    "Claude": (135, 165, 103),
    "Zero": (-245, 380, 103),
}
# Shot classes match the authored episode outline, but positions are
# **blocking guides**, not final approved camera/lens decisions.
SHOT_SCENE = (
    "hall","hall","hall","hall","hall","hall","hall","hall",
    "hall","hall","hall","hall","entrance","entrance","entrance",
    "entrance","entrance","entrance","entrance","entrance","entrance",
    "hall","hall","hall","hall","hall","hall","hall","hall","hall","hall",
)
SHOT_TARGET = (
    "Gemini","Gemini","DeepSeek","Gemini","Gemini","GPT",
    "GPT","DeepSeek","Claude","Claude","Claude","DeepSeek",
    "Zero","Zero","Zero","Zero","Zero","DeepSeek","Gemini",
    "Zero","Zero","Gemini","Claude","Gemini","GPT",
    "Screen","Gemini","DeepSeek","GPT","Screen","Zero",
)
assert len(SHOT_SCENE) == len(SHOT_TARGET) == 31


def vec(position):
    return unreal.Vector(float(position[0]), float(position[1]), float(position[2]))


def rot(pitch=0, yaw=0, roll=0):
    return unreal.Rotator(float(pitch), float(yaw), float(roll))


def new_cube(actors, mesh, label, position, scale):
    actor = actors.spawn_actor_from_class(
        unreal.StaticMeshActor, vec(position), rot()
    )
    if not actor:
        raise RuntimeError("could_not_spawn: " + label)
    actor.set_actor_label("V03_" + label)
    component = actor.get_component_by_class(unreal.StaticMeshComponent)
    if not component or not component.set_static_mesh(mesh):
        raise RuntimeError("could_not_assign_geometry: " + label)
    actor.set_actor_scale3d(vec(scale))
    return actor


def stage_level():
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if unreal.EditorAssetLibrary.does_asset_exist(STAGE_MAP):
        raise RuntimeError("v03_stage_map_already_exists_refuse_overwrite")
    for folder in (V03, V03 + "/Maps", SHOT_FOLDER, EPISODE_FOLDER):
        unreal.EditorAssetLibrary.make_directory(folder)
    if not editor.new_level(STAGE_MAP):
        raise RuntimeError("could_not_create_stage_map")
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    cube = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube.Cube")
    if not cube:
        raise RuntimeError("built_in_cube_missing")
    # Unreal basic cube size is 100cm on each axis.
    new_cube(actors,cube,"Hall_Floor",(150,0,-18),(13,13,0.2))
    new_cube(actors,cube,"Back_Wall",(800,0,250),(0.18,13,5.5))
    new_cube(actors,cube,"Side_Wall_Left",(150,-650,240),(13,0.18,5.2))
    new_cube(actors,cube,"Hall_Table",(110,-20,80),(4.1,2.7,0.14))
    new_cube(actors,cube,"Console_Screen",(430,225,145),(0.2,2.1,1.3))
    new_cube(actors,cube,"Entry_Frame_Left",(-360,315,170),(0.14,0.16,3.4))
    new_cube(actors,cube,"Entry_Frame_Right",(-360,515,170),(0.14,0.16,3.4))
    new_cube(actors,cube,"Entry_Frame_Top",(-360,415,340),(0.14,2.1,0.12))
    # Deliberately simple human stand-ins with unmistakable V03_Proxy labels.
    for label, position in STANDINS.items():
        new_cube(actors,cube,"Proxy_" + label,position,(0.55,0.55,1.8))
    for name, pos in (("Key",(-150,-300,450)),("Fill",(250,330,360))):
        light = actors.spawn_actor_from_class(
            unreal.PointLight, vec(pos), rot()
        )
        if not light:
            raise RuntimeError("could_not_spawn_light: " + name)
        light.set_actor_label("V03_" + name + "_Light")
        comp = light.get_component_by_class(unreal.PointLightComponent)
        if comp:
            comp.set_editor_property("intensity", 18000.0 if name=="Key" else 9000.0)
            comp.set_editor_property("attenuation_radius", 1600.0)
    if not editor.save_current_level():
        raise RuntimeError("could_not_save_stage_map")
    return actors


def camera_pose(index):
    scene = SHOT_SCENE[index]
    target = SHOT_TARGET[index]
    if target == "Screen":
        center = (425,225,160)
    else:
        center = STANDINS[target]
    # Fixed shot plan: alternate compositions and distances per shot,
    # with entrance views angled toward the door.
    if scene == "entrance":
        distance = (420, 520, 610)[index % 3]
        where = (-distance, 345 + (index % 2)*140, 225)
    else:
        distance = (410, 600, 860)[index % 3]
        where = (center[0]-distance, center[1] + ((index % 5)-2)*65, 185+((index%3)*35))
    return where, center, (35.0, 50.0, 70.0)[index%3]


def create_sequence(tools, package, name, frames, fps):
    path = package + "/" + name
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        raise RuntimeError("v03_sequence_already_exists_refuse_overwrite: " + name)
    sequence = tools.create_asset(
        asset_name=name, package_path=package,
        asset_class=unreal.LevelSequence,
        factory=unreal.LevelSequenceFactoryNew(),
    )
    if not sequence:
        raise RuntimeError("could_not_create_sequence: " + name)
    sequence.set_display_rate(unreal.FrameRate(numerator=fps, denominator=1))
    sequence.set_playback_start(0)
    sequence.set_playback_end(frames)
    return sequence


def add_camera(actors, sequence, index, frames):
    where, target, focal = camera_pose(index)
    actor = actors.spawn_actor_from_class(
        unreal.CineCameraActor,
        vec(where),
        unreal.MathLibrary.find_look_at_rotation(vec(where),vec(target)),
    )
    if not actor:
        raise RuntimeError("could_not_spawn_camera: " + str(index+1))
    actor.set_actor_label("V03_CAM_SH" + str(index+1).zfill(2))
    component = actor.get_component_by_class(unreal.CineCameraComponent)
    if component:
        component.set_editor_property("current_focal_length", focal)
    # The world actor is a possessable; it remains in the saved V03 map.
    binding = unreal.MovieSceneSequenceExtensions.add_possessable(sequence, actor)
    if not binding:
        raise RuntimeError("could_not_bind_camera")
    cut_track = sequence.add_track(unreal.MovieSceneCameraCutTrack)
    cut = cut_track.add_section()
    cut.set_range(0, frames)
    binding_id = unreal.MovieSceneSequenceExtensions.get_binding_id(sequence,binding)
    cut.set_camera_binding_id(binding_id)
    return actor


def build(spec):
    if spec.get("format") != "director_ue_stage_v03":
        raise RuntimeError("invalid_stage_spec")
    if spec.get("project_id") != "WaitingOffice" or spec.get("episode_id") != "EP01":
        raise RuntimeError("stage_template_not_approved_for_episode")
    if spec.get("fps") != 24 or len(spec.get("shots",[])) != 31:
        raise RuntimeError("stage_requires_locked_ep01_plan")
    if sum(s["frames"] for s in spec["shots"]) != 3840 or spec["total_frames"] != 3840:
        raise RuntimeError("stage_timing_not_3840")
    if unreal.EditorAssetLibrary.does_asset_exist(MASTER_PATH):
        raise RuntimeError("v03_master_already_exists_refuse_overwrite")
    actors = stage_level()
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    sequences = []
    for index, shot in enumerate(spec["shots"]):
        if shot["shot_id"] != str(index+1).zfill(2):
            raise RuntimeError("shot_id_order_not_frozen")
        name = "WaitingOffice_EP01_SH" + shot["shot_id"] + "_V03"
        seq = create_sequence(tools, SHOT_FOLDER,name,shot["frames"],24)
        add_camera(actors,seq,index,shot["frames"])
        if not unreal.EditorAssetLibrary.save_loaded_asset(seq):
            raise RuntimeError("could_not_save_v03_shot: " + name)
        sequences.append(seq)
    # The camera actors are placed in the stage level, and must be saved.
    editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not editor.save_current_level():
        raise RuntimeError("could_not_save_cameras_to_stage")
    master = create_sequence(tools, EPISODE_FOLDER,
                             "WaitingOffice_EP01_Master_V03",3840,24)
    shots_track = master.add_track(unreal.MovieSceneCinematicShotTrack)
    cursor = 0
    for shot, seq in zip(spec["shots"],sequences):
        part = shots_track.add_section()
        part.set_sequence(seq)
        part.set_range(cursor,cursor + shot["frames"])
        cursor += shot["frames"]
    if cursor != 3840 or not unreal.EditorAssetLibrary.save_loaded_asset(master):
        raise RuntimeError("could_not_save_v03_master")
    return {
        "ok": True,"stage_map": STAGE_MAP,"master": MASTER_PATH,
        "shot_count": len(sequences),"camera_count":len(sequences),
        "proxy_actor_count":len(STANDINS), "total_frames":cursor,
        "fps":24, "render_ready":False,
        "metahuman_bound":False, "audio_bound":False,
        "note":"Real stage geometry + per-shot cameras; actors are proxy blocks",
    }


def main():
    result_path = Path(os.environ["DIRECTOR_UE_RESULT_FILE"])
    try:
        spec_path = Path(os.environ["DIRECTOR_UE_SPEC_FILE"])
        result = build(json.loads(spec_path.read_text(encoding="utf-8")))
    except Exception as exc:
        result = {"ok":False,"reason":str(exc)[:400],
                  "traceback":traceback.format_exc(limit=5)[-2000:]}
    result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),
                           encoding="utf-8")
    if result["ok"]:
        unreal.log("V03 stage+camera assets saved")
    else:
        unreal.log_error("V03 build failed: " + result["reason"])


main()
