"""Offline fake-UE contract for V03 stage/camera creation.

The fake API intentionally exercises the documented UE 5.8 camera-cut and
sequence binding calls but cannot replace a real UE engine acceptance run.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

DURATIONS = [3,5,5,6,6,5,5,6,5,6,5,5,4,5,5,5,7,5,5,5,6,5,6,5,4,5,5,6,5,5,5]


class Component:
    def set_static_mesh(self, mesh):
        return bool(mesh)

    def set_editor_property(self, name, value):
        setattr(self, name, value)


class Actor:
    def __init__(self, kind, position, rotation):
        self.kind = kind
        self.position = position
        self.rotation = rotation
        self.components = {}
        self.label = None

    def set_actor_label(self, label):
        self.label = label

    def set_actor_scale3d(self, scale):
        self.scale = scale

    def get_component_by_class(self, kind):
        if kind not in self.components:
            self.components[kind] = Component()
        return self.components[kind]


class Section:
    def set_range(self, begin, end):
        self.range = (begin, end)

    def set_sequence(self, sequence):
        self.sequence = sequence

    def set_camera_binding_id(self, binding):
        self.camera_binding = binding


class Track:
    def __init__(self, kind):
        self.kind = kind
        self.sections = []

    def add_section(self):
        result = Section()
        self.sections.append(result)
        return result


class Sequence:
    def __init__(self):
        self.tracks = []
        self.bindings = []

    def set_display_rate(self, fps):
        self.fps = fps

    def set_playback_start(self, first):
        self.start = first

    def set_playback_end(self, last):
        self.last = last

    def add_track(self, kind):
        track = Track(kind)
        self.tracks.append(track)
        return track


def fake_ue(existing=None):
    assets = dict(existing or {})
    actors = []
    new_maps = []
    maps_saved = []
    camera_cut_class = object()
    cinematic_shot_class = object()

    def create_asset(*, asset_name, package_path, asset_class, factory):
        path = package_path + "/" + asset_name
        if path in assets:
            raise AssertionError("asset overwritten: " + path)
        result = Sequence()
        assets[path] = result
        return result

    def new_level(path):
        if path in assets:
            return False
        assets[path] = "saved-map-placeholder"
        new_maps.append(path)
        return True

    def spawn_actor_from_class(kind, position, rotation):
        result = Actor(kind,position,rotation)
        actors.append(result)
        return result

    library = types.SimpleNamespace(
        does_asset_exist=lambda path: path in assets,
        make_directory=lambda path: True,
        load_asset=lambda path: "engine-cube" if path == "/Engine/BasicShapes/Cube.Cube" else assets.get(path),
        save_loaded_asset=lambda asset: True,
    )
    level = types.SimpleNamespace(
        new_level=new_level,
        save_current_level=lambda: maps_saved.append(True) or True,
    )
    actor_system = types.SimpleNamespace(spawn_actor_from_class=spawn_actor_from_class)
    level_type = object()
    actor_type = object()
    fake = types.SimpleNamespace(
        EditorAssetLibrary=library,
        AssetToolsHelpers=types.SimpleNamespace(
            get_asset_tools=lambda: types.SimpleNamespace(create_asset=create_asset)
        ),
        LevelEditorSubsystem=level_type,
        EditorActorSubsystem=actor_type,
        get_editor_subsystem=lambda kind: level if kind is level_type else actor_system,
        Vector=lambda *position: tuple(position),
        Rotator=lambda *rotation: tuple(rotation),
        StaticMeshActor="mesh-actor",
        StaticMeshComponent="mesh-component",
        PointLight="light-actor",
        PointLightComponent="light-component",
        CineCameraActor="camera-actor",
        CineCameraComponent="camera-component",
        MathLibrary=types.SimpleNamespace(find_look_at_rotation=lambda a,b: ("look_at",a,b)),
        MovieSceneSequenceExtensions=types.SimpleNamespace(
            add_possessable=lambda sequence, actor: sequence.bindings.append(actor) or actor,
            get_binding_id=lambda sequence,binding: ("binding",id(sequence),id(binding)),
        ),
        MovieSceneCinematicShotTrack=cinematic_shot_class,
        MovieSceneCameraCutTrack=camera_cut_class,
        LevelSequence=Sequence,
        LevelSequenceFactoryNew=lambda: object(),
        FrameRate=lambda **kwargs: kwargs,
        log=lambda message: None,
        log_error=lambda message: None,
    )
    return fake, assets, actors, new_maps, maps_saved, camera_cut_class, cinematic_shot_class


def studio_plan():
    frames = [x*24 for x in DURATIONS]
    assert sum(frames) == 3840
    return {
        "format": "director_ue_stage_v03",
        "project_id": "WaitingOffice", "episode_id": "EP01", "fps":24,
        "shots": [
            {"shot_id": f"{i:02}", "frames": frame}
            for i,frame in enumerate(frames, 1)
        ],
        "total_frames":3840,
    }


def execute(fake, data):
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp)
        plan=folder/"plan.json"
        result=folder/"result.json"
        plan.write_text(json.dumps(data),encoding="utf-8")
        with patch.dict(sys.modules, {"unreal":fake}),patch.dict(
            os.environ,{"DIRECTOR_UE_SPEC_FILE":str(plan),
                        "DIRECTOR_UE_RESULT_FILE":str(result)}
        ):
            path=Path(__file__).resolve().parents[1]/"unreal_build_stage.py"
            spec=importlib.util.spec_from_file_location("mock_v03_builder",path)
            module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return json.loads(result.read_text(encoding="utf-8"))


class V03StageTest(unittest.TestCase):
    def test_creates_separate_map_31_cameras_and_master(self):
        old="/Game/Director/Episodes/WaitingOffice_EP01_Master"
        marker=object()
        fake, assets, actors, maps, saved, cut_track, shot_track = fake_ue({old:marker})
        result=execute(fake,studio_plan())
        self.assertTrue(result["ok"],result.get("reason"))
        self.assertIs(assets[old],marker)
        self.assertEqual(result["total_frames"],3840)
        self.assertEqual(result["shot_count"],31)
        self.assertEqual(result["camera_count"],31)
        self.assertFalse(result["metahuman_bound"])
        self.assertFalse(result["render_ready"])
        self.assertEqual(len(maps),1)
        self.assertGreaterEqual(len(saved),2)
        cameras=[actor for actor in actors if actor.kind=="camera-actor"]
        standins=[actor for actor in actors if (actor.label or "").startswith("V03_Proxy_")]
        self.assertEqual(len(cameras),31)
        self.assertEqual(len(standins),5)
        camera_sequence=assets["/Game/Director/V03/Shots/WaitingOffice_EP01_SH01_V03"]
        self.assertEqual(len(camera_sequence.bindings),1)
        self.assertIs(camera_sequence.tracks[0].kind,cut_track)
        self.assertEqual(camera_sequence.tracks[0].sections[0].range,(0,72))
        self.assertIsNotNone(camera_sequence.tracks[0].sections[0].camera_binding)
        master=assets["/Game/Director/V03/Episodes/WaitingOffice_EP01_Master_V03"]
        self.assertIs(master.tracks[0].kind,shot_track)
        self.assertEqual(len(master.tracks[0].sections),31)
        self.assertEqual(master.tracks[0].sections[-1].range,(3720,3840))

    def test_refuses_overwrite_of_existing_v03(self):
        master="/Game/Director/V03/Episodes/WaitingOffice_EP01_Master_V03"
        fake, assets, actors, maps, saved, *_ = fake_ue({master:object()})
        result=execute(fake,studio_plan())
        self.assertFalse(result["ok"])
        self.assertIn("already_exists",result["reason"])
        self.assertEqual(len(maps),0)

    def test_rejects_different_episode_template(self):
        fake, assets, actors, maps, saved, *_ = fake_ue()
        spec=studio_plan()
        spec["episode_id"]="EP02"
        result=execute(fake,spec)
        self.assertFalse(result["ok"])
        self.assertEqual(maps,[])


if __name__ == "__main__":
    unittest.main()
