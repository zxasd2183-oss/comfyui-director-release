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



# V0.8: fixed, read-only inventory for the director-approved PRODUCTION assets.
# V03 cubes and preview stages cannot satisfy these asset paths.
APPROVED_ROOT = "/Game/Director/Approved"


def audit_ep01_assets(spec):
    """Inspect native Unreal assets only; never create, save, render or approve."""
    if (spec.get("format") != "director_ue_assets_v08" or
            (spec.get("project_id"), spec.get("episode_id"), spec.get("fps"),
             spec.get("total_ms"), spec.get("total_frames")) !=
            ("WaitingOffice", "EP01", 24, 160000, 3840)):
        raise RuntimeError("audit_requires_frozen_ep01")
    if (len(spec.get("shots", [])) != 31 or
            [s.get("shot_id") for s in spec["shots"]] !=
            ["%02d" % i for i in range(1,32)] or
            sum(s["frames"] for s in spec["shots"]) != 3840):
        raise RuntimeError("audit_requires_complete_31_shots")

    expectations = {
        "characters": [
            ("CHAR_GPT", {"Blueprint", "SkeletalMesh"}),
            ("CHAR_GEM", {"Blueprint", "SkeletalMesh"}),
            ("CHAR_DS", {"Blueprint", "SkeletalMesh"}),
            ("CHAR_CLA", {"Blueprint", "SkeletalMesh"}),
            ("CHAR_ZERO", {"Blueprint", "SkeletalMesh"}),
        ],
        "scenes": [
            ("SCN_HALL", {"World"}),
            ("SCN_ENTRANCE", {"World"}),
        ],
        "shots": [
            ("SH%02d" % i, {"LevelSequence"}) for i in range(1, 32)
        ],
    }
    directories = {
        "characters": APPROVED_ROOT + "/Characters/",
        "scenes": APPROVED_ROOT + "/Scenes/",
        "shots": APPROVED_ROOT + "/EP01/Shots/",
    }
    report = {}
    for kind, objects in expectations.items():
        group = []
        for label, classes in objects:
            path = directories[kind] + label
            exists = bool(unreal.EditorAssetLibrary.does_asset_exist(path))
            valid = False
            if exists:
                # Class inspection is necessary, NOT sufficient to call this
                # approved, bound, playable or eligible for final rendering.
                obj = unreal.EditorAssetLibrary.load_asset(path)
                if obj is not None:
                    cls = obj.get_class()
                    valid = bool(cls is not None and cls.get_name() in classes)
            group.append({"id":label, "exists":exists, "type_valid":valid})
        report[kind] = group
    return {
        "ok": True,
        "shot_count": 31, "total_frames": 3840,
        "asset_audit": report,
    }




# V0.9: ORIGINAL, EDITABLE SCENE CANDIDATES. These are authored UE geometry
# and materials, NOT the retired gray V03 stand-ins, downloaded art, or
# approved character masters. Never edit V03 or /Game/Director/Approved.
SCENE_IDS = ("SCN_HALL", "SCN_HALL_ALERT", "SCN_ENTRANCE")
SCENE_COLORS = {
    "Milk": (0.89, 0.86, 0.77),      # warm off-white surfaces
    "Mint": (0.43, 0.69, 0.57),      # cabinetry and accent wall
    "Oak": (0.54, 0.32, 0.17),       # long wooden desk
    "Charcoal": (0.13, 0.18, 0.21),  # window and console frames
    "BlueGlass": (0.30, 0.63, 0.78), # deliberately stylized glass
    "Leaf": (0.14, 0.45, 0.27),      # plants
    "Coral": (0.83, 0.26, 0.25),     # alert light and accent
    "Paper": (0.95, 0.92, 0.82),
    "Gold": (0.82, 0.61, 0.28),
    "Slate": (0.39, 0.48, 0.53),
}
SCENE_GEOMETRY = {
    "Cube": "/Engine/BasicShapes/Cube.Cube",
    "Sphere": "/Engine/BasicShapes/Sphere.Sphere",
    "Cylinder": "/Engine/BasicShapes/Cylinder.Cylinder",
}


def _create_scene_materials(directory):
    """Create actual UE Material assets with authored matte palette."""
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    materials = {}
    for name, rgb in SCENE_COLORS.items():
        path = directory + "/M_" + name
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            raise RuntimeError("candidate_material_collision")
        material = tools.create_asset(
            asset_name="M_" + name, package_path=directory,
            asset_class=unreal.Material, factory=unreal.MaterialFactoryNew()
        )
        if not material:
            raise RuntimeError("scene_material_creation_failed_" + name)
        color = unreal.MaterialEditingLibrary.create_material_expression(
            material, unreal.MaterialExpressionConstant3Vector
        )
        if not color:
            raise RuntimeError("scene_material_expression_failed_" + name)
        color.set_editor_property("constant", unreal.LinearColor(
            float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0
        ))
        unreal.MaterialEditingLibrary.connect_material_property(
            color, "", unreal.MaterialProperty.MP_BASE_COLOR
        )
        roughness = unreal.MaterialEditingLibrary.create_material_expression(
            material, unreal.MaterialExpressionConstant
        )
        if not roughness:
            raise RuntimeError("scene_roughness_expression_failed_" + name)
        roughness.set_editor_property("r", 0.88)
        unreal.MaterialEditingLibrary.connect_material_property(
            roughness, "", unreal.MaterialProperty.MP_ROUGHNESS
        )
        unreal.MaterialEditingLibrary.recompile_material(material)
        if not unreal.EditorAssetLibrary.save_loaded_asset(material):
            raise RuntimeError("scene_material_save_failed_" + name)
        materials[name] = material
    return materials


def _populate_scene(scene_id, materials, meshes):
    """World-space positions keep the V03 door/table/terminal anchors."""
    editor_actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    props, lights, cameras = [], [], []

    def part(label, kind, xyz, dims, material):
        if kind not in SCENE_GEOMETRY or material not in materials:
            raise RuntimeError("invalid_authored_scene_part")
        actor = editor_actors.spawn_actor_from_class(
            unreal.StaticMeshActor, vec(xyz), rot()
        )
        if not actor:
            raise RuntimeError("candidate_actor_spawn_failed_" + label)
        actor.set_actor_label("WO09_" + label)
        component = actor.get_component_by_class(unreal.StaticMeshComponent)
        if not component or not component.set_static_mesh(meshes[kind]):
            raise RuntimeError("candidate_mesh_assignment_failed_" + label)
        component.set_material(0, materials[material])
        actor.set_actor_scale3d(vec(dims))
        props.append(label)

    def point(name, xyz, intensity, color_name="Paper"):
        light = editor_actors.spawn_actor_from_class(
            unreal.PointLight, vec(xyz), rot()
        )
        if not light:
            raise RuntimeError("candidate_light_spawn_failed_" + name)
        light.set_actor_label("WO09_" + name)
        component = light.get_component_by_class(unreal.PointLightComponent)
        if not component:
            raise RuntimeError("candidate_light_component_missing")
        component.set_editor_property("intensity", float(intensity))
        component.set_editor_property("attenuation_radius", 1450.0)
        # Material palette handles the scene's stylized color design;
        # no external HDRI, environment texture or unapproved asset used.
        lights.append(name)

    def view(name, xyz, target, focal_mm):
        actor = editor_actors.spawn_actor_from_class(
            unreal.CineCameraActor, vec(xyz),
            unreal.MathLibrary.find_look_at_rotation(vec(xyz), vec(target))
        )
        if not actor:
            raise RuntimeError("candidate_camera_spawn_failed_" + name)
        actor.set_actor_label("WO09_" + name)
        camera = actor.get_component_by_class(unreal.CineCameraComponent)
        if not camera:
            raise RuntimeError("candidate_camera_component_missing")
        camera.set_editor_property("current_focal_length", float(focal_mm))
        cameras.append(name)

    # Shared architecture. Intentionally open roof for editorial review.
    part("Floor", "Cube", (150, 0, -15), (13.0, 13.0, .24), "Milk")
    part("North_Wall", "Cube", (150, 645, 230), (13.0, .16, 4.9), "Mint")
    part("South_Wall", "Cube", (150, -645, 230), (13.0, .16, 4.9), "Milk")
    part("East_Wall", "Cube", (795, 0, 230), (.16, 13.0, 4.9), "Milk")
    part("Baseboard_North", "Cube", (150, 625, 12), (13.0, .12, .23), "Oak")
    part("Baseboard_South", "Cube", (150, -625, 12), (13.0, .12, .23), "Oak")
    part("Rug", "Cube", (90, -50, 2), (5.5, 3.8, .03), "Paper")

    # Door hinge/handle and hand-axis stay consistent with SH13-21.
    part("Door_Left_Jamb", "Cube", (-360, 304, 173), (.20, .17, 3.45), "Charcoal")
    part("Door_Right_Jamb", "Cube", (-360, 515, 173), (.20, .17, 3.45), "Charcoal")
    part("Door_Header", "Cube", (-360, 408, 346), (.20, 2.2, .16), "Charcoal")
    part("Door_Glass_Panel", "Cube", (-360, 406, 170), (.035, 1.83, 3.05), "BlueGlass")
    part("Door_Horizontal_Trim", "Cube", (-358, 407, 90), (.055, 1.83, .045), "Slate")
    part("Door_Handle", "Cylinder", (-355, 475, 105), (.06, .06, .27), "Gold")

    entrance = scene_id == "SCN_ENTRANCE"
    warning = scene_id == "SCN_HALL_ALERT"
    if not entrance:
        # Long office table: top, legs, chairs, individual hero props.
        part("Oak_Tabletop", "Cube", (110, -20, 82), (4.2, 2.7, .14), "Oak")
        for xside, x in (("L", -70), ("R", 285)):
            for yside, y in (("F", -115), ("B", 75)):
                part("Table_Leg_"+xside+yside, "Cube",
                     (x,y,41), (.14, .16, .82), "Charcoal")
        for label, x, y in (("Gemini", -120, -195),
                            ("DeepSeek", 95, -206),
                            ("Claude", 300, 180)):
            part("Chair_Base_"+label, "Cylinder",
                 (x,y,27), (.56,.56,.13), "Slate")
            part("Chair_Back_"+label, "Cube",
                 (x,y+35,85), (.65,.12,1.13), "Mint")
        part("Cup_Body", "Cylinder", (105, 30, 102), (.24,.24,.32), "Paper")
        part("Cup_Saucer", "Cylinder", (105, 30, 87), (.44,.44,.05), "Gold")
        part("Book_Cover", "Cube", (305, 148, 92), (.46,.64,.08), "Coral")
        for n in range(4):
            part("Paper_Sheet_%02d"%n, "Cube",
                 (12+n*18,-35+n*4,93+n*2), (.40,.54,.008), "Paper")

        # Sofa, tea table, shelves and distinct colored books.
        part("Sofa_Seat", "Cube", (-215,-405,45), (3.4,1.25,.65), "Mint")
        part("Sofa_Back", "Cube", (-215,-463,112), (3.4,.26,1.2), "Mint")
        part("Tea_Table", "Cube", (-160,-245,39), (2.1,.92,.18), "Oak")
        part("Shelf_Frame", "Cube", (647,-475,181), (.65,2.1,3.4), "Oak")
        for n in range(4):
            part("Shelf_Lip_%02d"%n, "Cube",
                 (609,-475,42+n*82), (.8,2.2,.10), "Charcoal")
        for n in range(12):
            part("Book_Spine_%02d"%n, "Cube",
                 (598,-545+(n%6)*22,64+(n//6)*86),
                 (.17,.16,.43), ["Gold","Mint","Coral","BlueGlass"][n%4])
        part("Plant_Pot", "Cylinder", (585,485,50), (.66,.66,.9), "Oak")
        part("Plant_Stem", "Cylinder", (585,485,140), (.10,.10,1.3), "Leaf")
        for n,(dx,dy) in enumerate(((35,0),(-35,10),(10,40),(-10,-35))):
            part("Plant_Leaf_%02d"%n, "Sphere",
                 (585+dx,485+dy,195+n*10),(.70,.40,.12), "Leaf")

        # Physically consistent, unlettered control monitor at the rear.
        part("Terminal_Stand", "Cube", (427,225,71),(.23,.28,1.3), "Slate")
        part("Terminal_Screen", "Cube", (431,225,151),(.09,1.95,1.22), "Charcoal")
        part("Terminal_Inset", "Cube", (421,225,152),(.02,1.74,.99), "BlueGlass")
        for n,y in enumerate((-340,-95,150)):
            part("Window_Frame_%02d"%n, "Cube",
                 (783,y,219),(.11,1.9,2.8), "Charcoal")
            part("Window_Pane_%02d"%n, "Cube",
                 (772,y,225),(.018,1.67,2.5), "BlueGlass")
        point("Key_Light",(-150,-260,440),850)
        point("Fill_Light",(260,390,390),480)
        point("Window_Bounce",(610,-190,410),620)
        if warning:
            part("Ceiling_Alert_Bar", "Cube", (110,-20,355),
                 (2.4,.28,.10), "Coral")
            point("Warning_Light",(140,-30,410),1200,"Coral")
        else:
            part("Pendant_Lamp", "Cylinder",(110,-20,345),
                 (.72,.72,.25),"Gold")
        view("Hall_Master_Camera",(-500,-440,265),(130,-35,120),28)
        view("Console_Insert_Camera",(-245,85,220),(430,225,150),42)
    else:
        # Foyer layout: glazing, patterned floor strip, city silhouettes
        # beyond the door. No live external street/brand imagery.
        part("Foyer_Runner", "Cube",(-450,404,3),(4.5,1.3,.04),"Slate")
        for n in range(7):
            part("City_Massing_%02d"%n,"Cube",
                 (-880-n*45,260+n*55,140+n%3*45),
                 (.95,.55,2.6+n%3*.8),"BlueGlass")
        part("Coat_Rack", "Cylinder",(-125,545,140),(.13,.13,2.7),"Oak")
        for n in range(3):
            part("Coat_Hook_%02d"%n,"Cube",
                 (-125,545+(n-1)*34,260),(.42,.10,.08),"Gold")
        part("Entry_Side_Table", "Cube",(-175,150,62),(1.5,.68,.15),"Oak")
        part("Entry_Wait_Seat", "Cube",(-40,240,48),(1.50,.74,.55),"Mint")
        part("Entry_Bench_Back", "Cube",(-40,270,99),(1.5,.14,.85),"Mint")
        for n in range(4):
            part("Floor_Inlay_%02d"%n,"Cube",
                 (-610+n*72,410,6),(.34,1.1,.025),"Gold")
        point("Door_Daylight",(-520,350,385),860)
        point("Entry_Fill",(-110,65,330),520)
        view("Entrance_Master_Camera",(-890,345,225),
             (-250,410,135),27)
        view("Entrance_Reverse_Camera",(80,350,205),
             (-470,408,120),35)

    return {"props":len(props),"lights":len(lights),
            "review_cameras":len(cameras)}


def build_ep01_scene_candidates(spec):
    """Create job-isolated ORIGINAL environment assets without approvals."""
    import re
    if (spec.get("format") != "director_ue_scene_candidates_v09" or
            (spec.get("project_id"),spec.get("episode_id"),spec.get("fps"),
             spec.get("total_ms"),spec.get("total_frames")) !=
            ("WaitingOffice","EP01",24,160000,3840)):
        raise RuntimeError("scene_candidates_require_frozen_ep01")
    if (len(spec.get("shots",[]))!=31 or
            [s.get("shot_id") for s in spec["shots"]] !=
            ["%02d"%i for i in range(1,32)] or
            sum(s["frames"] for s in spec["shots"]) != 3840):
        raise RuntimeError("scene_candidates_plan_invalid")
    job_id = os.environ.get("DIRECTOR_UE_JOB_ID","")
    if not re.fullmatch(r"[a-f0-9]{32}",job_id):
        raise RuntimeError("scene_candidates_job_id_invalid")
    base="/Game/Director/Candidates/EP01/SceneBuilds/J"+job_id
    if unreal.EditorAssetLibrary.does_directory_exist(base):
        raise RuntimeError("scene_candidates_job_namespace_collision")
    # Prevent an existing approved master from being mistaken for our draft.
    for name in ("SCN_HALL","SCN_ENTRANCE"):
        if unreal.EditorAssetLibrary.does_asset_exist(
                "/Game/Director/Approved/Scenes/"+name):
            raise RuntimeError("approved_scene_exists_use_reviewed_revision")
    materials_dir=base+"/Materials"
    maps_dir=base+"/Maps"
    if not unreal.EditorAssetLibrary.make_directory(materials_dir):
        raise RuntimeError("candidate_material_directory_failed")
    if not unreal.EditorAssetLibrary.make_directory(maps_dir):
        raise RuntimeError("candidate_map_directory_failed")
    mats=_create_scene_materials(materials_dir)
    meshes={kind:unreal.EditorAssetLibrary.load_asset(path)
            for kind,path in SCENE_GEOMETRY.items()}
    if any(item is None for item in meshes.values()):
        raise RuntimeError("unreal_basic_shape_missing")
    editor=unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    result=[]
    for scene_id in SCENE_IDS:
        path=maps_dir+"/"+scene_id
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            raise RuntimeError("candidate_scene_output_collision")
        if not editor.new_level(path):
            raise RuntimeError("candidate_scene_create_failed_"+scene_id)
        summary=_populate_scene(scene_id,mats,meshes)
        if summary["props"] < 20 or summary["lights"] < 2 or summary["review_cameras"] < 2:
            raise RuntimeError("candidate_scene_underspecified_"+scene_id)
        if not editor.save_current_level():
            raise RuntimeError("candidate_scene_save_failed_"+scene_id)
        if not unreal.EditorAssetLibrary.does_asset_exist(path):
            raise RuntimeError("candidate_scene_missing_after_save_"+scene_id)
        result.append({"id":scene_id,"path":path,**summary})
    return {"ok":True,"candidate_kind":"original_editable_environment_v09",
            "scene_candidates":result,"material_count":len(mats),
            "shot_count":31,"total_frames":3840,
            "studio_scene_approval_verified":False,
            "character_models_bound":False,"render_ready":False,
            "no_existing_scene_replaced":True}



def main():
    result_path = Path(os.environ["DIRECTOR_UE_RESULT_FILE"])
    try:
        spec_path = Path(os.environ["DIRECTOR_UE_SPEC_FILE"])
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        result = (audit_ep01_assets(spec)
                  if spec.get("format") == "director_ue_assets_v08"
                  else build_ep01_scene_candidates(spec)
                  if spec.get("format") == "director_ue_scene_candidates_v09"
                  else build(spec))
    except Exception as exc:
        result = {"ok":False,"reason":str(exc)[:400],
                  "traceback":traceback.format_exc(limit=5)[-2000:]}
    result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),
                           encoding="utf-8")
    if result["ok"]:
        unreal.log("Scene candidates created under job-owned namespace" if
                   result.get("scene_candidates") is not None else
                   "Approved-asset inspection complete (no writes)" if
                   result.get("asset_audit") is not None else
                   "V03 stage+camera assets saved")
    else:
        unreal.log_error("V03 build failed: " + result["reason"])


main()
