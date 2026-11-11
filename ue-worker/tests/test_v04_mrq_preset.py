"""Fake-UE contract for the fixed MRQ preview preset.

This verifies the intended asset and settings. Only a real UE5.8 execution
can prove the commandline MRQ runtime actually renders PNG frames.
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


class FakeSetting:
    def __init__(self):
        self.props={}

    def set_editor_property(self,name,value):
        self.props[name]=value


class FakeConfig:
    def __init__(self):
        self.settings={}

    def find_or_add_setting_by_class(self,klass):
        if klass not in self.settings:
            self.settings[klass]=FakeSetting()
        return self.settings[klass]


class FakeCut:
    def __init__(self):
        self.range = None
        self.camera_binding_id = None
    def set_range(self, start, stop):
        self.range = (start, stop)
    def set_camera_binding_id(self, binding_id):
        self.camera_binding_id = binding_id


class FakeTrack:
    def __init__(self):
        self.cut = FakeCut()
    def add_section(self):
        return self.cut


class FakeSequence:
    def __init__(self):
        self.track = None
        self.camera = None
        self.display_rate = None
        self.playback = {}
    def set_display_rate(self, rate):
        self.display_rate = rate
    def set_playback_start(self, frame):
        self.playback["start"] = frame
    def set_playback_end(self, frame):
        self.playback["end"] = frame
    def add_track(self, cls):
        self.track = FakeTrack()
        return self.track


class PreviewPresetTest(unittest.TestCase):
    def test_mrq_preset_has_png_deferred_single_frame_and_720x1280(self):
        assets={}
        created=[]
        sequence_class = type("LevelSequence", (), {})
        def create_asset(*,asset_name,package_path,asset_class,factory):
            name=package_path+"/"+asset_name
            self.assertNotIn(name,assets)
            result = FakeSequence() if asset_class is sequence_class else FakeConfig()
            assets[name]=result
            created.append(name)
            return result
        config_class=object()
        deferred_class=object()
        png_class=object()
        output_class=object()
        class FakeLightComponent:
            def __init__(self,value):
                self.props={"intensity":value}
            def get_editor_property(self,name):
                return self.props[name]
            def set_editor_property(self,name,value):
                self.props[name]=value

        class FakeLightActor:
            def __init__(self,label,intensity):
                self.label=label
                self.light=FakeLightComponent(intensity)
            def get_actor_label(self):
                return self.label
            def get_component_by_class(self,_type):
                return self.light

        class FakeVector:
            def __init__(self,x,y,z):
                self.x,self.y,self.z=x,y,z
        class FakeCameraActor:
            def __init__(self,shot):
                self.shot = shot
                self.location=FakeVector(-420.0,345.0,225.0) if shot == "13" else FakeVector(-630,250,180)
                self.rotation=None
            def get_actor_label(self):
                return "V03_CAM_SH" + self.shot
            def get_component_by_class(self,kind):
                return self if kind is fake.CineCameraComponent else None
            def get_actor_location(self):
                return self.location
            def set_actor_location_and_rotation(self,new_location,new_rotation,sweep,teleport):
                assert not sweep and teleport
                self.location=new_location
                self.rotation=new_rotation
        cameras = {shot: FakeCameraActor(shot) for shot in ("01", "13", "26", "31")}
        camera13 = cameras["13"]
        original_map="/Game/Director/V03/Maps/WaitingOffice_EP01_Stage"
        stage_actors=[
            FakeLightActor("V03_Key_Light",18000.0),
            FakeLightActor("V03_Fill_Light",9000.0),
            *cameras.values(),
        ]
        class FakeLevel:
            cloned_from=None
            stage_path=None
            def new_level_from_template(self,dest,source):
                self.stage_path=dest
                self.cloned_from=source
                assets[dest]=object()
                return True
            def save_current_level(self):
                return True
        level=FakeLevel()
        editor_actor_subsystem=types.SimpleNamespace(
            get_all_level_actors=lambda:stage_actors
        )
        subsystems={}
        def get_subsystem(cls):
            return subsystems[cls]
        fake=types.SimpleNamespace(
            EditorAssetLibrary=types.SimpleNamespace(
                make_directory=lambda path: True,
                does_directory_exist=lambda path: False,
                does_asset_exist=lambda path: path in assets,
                save_loaded_asset=lambda config: True,
            ),
            MoviePipelinePrimaryConfigFactory=lambda: object(),
            AssetToolsHelpers=types.SimpleNamespace(
                get_asset_tools=lambda: types.SimpleNamespace(
                    create_asset=create_asset
                )
            ),
            MoviePipelinePrimaryConfig=config_class,
            MoviePipelineDeferredPassBase=deferred_class,
            MoviePipelineImageSequenceOutput_PNG=png_class,
            MoviePipelineOutputSetting=output_class,
            LevelSequence=sequence_class,
            LevelSequenceFactoryNew=lambda: object(),
            FrameRate=lambda numerator,denominator: (numerator,denominator),
            MovieSceneCameraCutTrack=type("MovieSceneCameraCutTrack",(),{}),
            MovieSceneSequenceExtensions=types.SimpleNamespace(
                add_possessable=lambda sequence,actor: setattr(sequence,"camera",actor) or ("binding",actor.shot),
                get_binding_id=lambda sequence,binding: ("camera_binding",binding[1]),
            ),
            LevelEditorSubsystem=type("LevelEditorSubsystem",(),{}),
            EditorActorSubsystem=type("EditorActorSubsystem",(),{}),
            PointLightComponent=type("PointLightComponent",(),{}),
            CineCameraComponent=type("CineCameraComponent",(),{}),
            Vector=FakeVector,
            MathLibrary=types.SimpleNamespace(
                find_look_at_rotation=lambda start,target: ("look_at",start,target)
            ),
            get_editor_subsystem=get_subsystem,
            DirectoryPath=lambda path: ("DirectoryPath",path),
            IntPoint=lambda x,y: (x,y),
            log=lambda message: None,
            log_error=lambda message: None,
        )
        subsystems[fake.LevelEditorSubsystem]=level
        subsystems[fake.EditorActorSubsystem]=editor_actor_subsystem
        assets[original_map]=object()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            jobid="a"*32
            output=root/"Outputs"/"V04"/jobid/"Previews"
            output.mkdir(parents=True)
            original_file=root/"Content"/"Director"/"V03"/"Maps"/"WaitingOffice_EP01_Stage.umap"
            original_file.parent.mkdir(parents=True)
            original_file.write_bytes(b"original-v03-map")
            result_path=root/"result.json"
            with patch.dict(
                sys.modules,{"unreal":fake}
            ),patch.dict(os.environ,{
                "DIRECTOR_UE_RESULT_FILE":str(result_path),
                "DIRECTOR_UE_JOB_ID":jobid,
                "DIRECTOR_UE_PREVIEW_OUTPUT":str(output),
            }):
                script=Path(__file__).resolve().parents[1]/"unreal_create_previs_preset.py"
                spec=importlib.util.spec_from_file_location("mrq_preset_fake",script)
                module=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            result=json.loads(result_path.read_text())
            self.assertTrue(result["ok"],result.get("reason"))
            self.assertEqual(result["frames_per_shot"],1)
            self.assertEqual(level.cloned_from, original_map)
            self.assertEqual(result["stage_map"], level.stage_path)
            self.assertIn("/Game/Director/V051/Maps/",level.stage_path)
            self.assertEqual(stage_actors[0].light.props["intensity"],800.0)
            self.assertEqual(stage_actors[1].light.props["intensity"],400.0)
            self.assertEqual((camera13.location.x,camera13.location.y,camera13.location.z),
                             (-860.0,345.0,225.0))
            self.assertIsNotNone(camera13.rotation)
            self.assertEqual(result["camera13_reframe"]["original"],
                             [-420.0,345.0,225.0])
            self.assertEqual(result["camera13_reframe"]["preview"],
                             [-860.0,345.0,225.0])
            self.assertEqual(original_file.read_bytes(), b"original-v03-map")
            self.assertEqual(result["height"],1280)
            self.assertEqual(len(created),5)
            expected = {
                shot: "/Game/Director/V071/ShotBindings/" + jobid +
                      "/WaitingOffice_EP01_SH" + shot + "_V03.WaitingOffice_EP01_SH" + shot + "_V03"
                for shot in ("01","13","26","31")
            }
            self.assertEqual(result["bound_preview_sequences"], expected)
            for shot, path in expected.items():
                sequence = assets[path.rsplit(".",1)[0]]
                self.assertIs(sequence.camera, cameras[shot])
                self.assertEqual(sequence.display_rate,(24,1))
                self.assertEqual(sequence.playback,{"start":0,"end":3})
                self.assertEqual(sequence.track.cut.range,(0,3))
                self.assertEqual(sequence.track.cut.camera_binding_id,
                                 ("camera_binding",shot))
            config=assets[created[0]]
            self.assertIn(deferred_class,config.settings)
            self.assertIn(png_class,config.settings)
            setting=config.settings[output_class].props
            self.assertEqual(setting["output_resolution"],(720,1280))
            self.assertEqual(setting["custom_start_frame"],0)
            self.assertEqual(setting["custom_end_frame"],1)
            self.assertFalse(setting["override_existing_output"])
            self.assertEqual(setting["output_directory"],("DirectoryPath",str(output)))


if __name__ == "__main__":
    unittest.main()
