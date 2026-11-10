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


class PreviewPresetTest(unittest.TestCase):
    def test_mrq_preset_has_png_deferred_single_frame_and_720x1280(self):
        assets={}
        created=[]
        def create_asset(*,asset_name,package_path,asset_class,factory):
            name=package_path+"/"+asset_name
            self.assertNotIn(name,assets)
            result=FakeConfig()
            assets[name]=result
            created.append(name)
            return result
        config_class=object()
        deferred_class=object()
        png_class=object()
        output_class=object()
        fake=types.SimpleNamespace(
            EditorAssetLibrary=types.SimpleNamespace(
                make_directory=lambda path: True,
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
            DirectoryPath=lambda path: ("DirectoryPath",path),
            IntPoint=lambda x,y: (x,y),
            log=lambda message: None,
            log_error=lambda message: None,
        )
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            jobid="a"*32
            output=root/jobid/"Previews"
            output.mkdir(parents=True)
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
            self.assertEqual(result["height"],1280)
            self.assertEqual(len(created),1)
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
