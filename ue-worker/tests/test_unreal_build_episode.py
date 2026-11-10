"""Exercise bundled Unreal Python script against a controlled fake API.

This proves the 31 sub-sequence construction logic without pretending to have
executed the real Unreal Editor or validated its binary plugins.
"""
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeSection:
    def __init__(self):
        self.sequence = None
        self.range = None

    def set_sequence(self, sequence):
        self.sequence = sequence

    def set_range(self, begin, end):
        self.range = (begin, end)


class FakeTrack:
    def __init__(self):
        self.sections = []

    def add_section(self):
        result = FakeSection()
        self.sections.append(result)
        return result


class FakeSequence:
    def __init__(self):
        self.start = 0
        self.end = 150
        self.fps = None
        self.tracks = []

    def set_display_rate(self, fps):
        self.fps = fps

    def set_playback_start(self, start):
        self.start = start

    def set_playback_end(self, end):
        self.end = end

    def get_playback_end(self):
        return self.end

    def add_track(self, klass):
        result = FakeTrack()
        self.tracks.append(result)
        return result


class UnrealScriptTest(unittest.TestCase):
    def test_creates_31_timed_sections_and_saves_master(self):
        assets = {}
        def create_asset(*, asset_name, package_path, asset_class, factory):
            path = package_path + "/" + asset_name
            asset = FakeSequence()
            assets[path] = asset
            return asset
        library = types.SimpleNamespace(
            does_asset_exist=lambda path: path in assets,
            load_asset=lambda path: assets[path],
            make_directory=lambda path: True,
            save_loaded_asset=lambda asset: True,
        )
        unreal = types.SimpleNamespace(
            EditorAssetLibrary=library,
            AssetToolsHelpers=types.SimpleNamespace(
                get_asset_tools=lambda: types.SimpleNamespace(create_asset=create_asset)
            ),
            LevelSequence=FakeSequence,
            LevelSequenceFactoryNew=lambda: object(),
            FrameRate=lambda **kwargs: kwargs,
            MovieSceneCinematicShotTrack=object,
            log=lambda message: None,
            log_error=lambda message: None,
        )
        durations = [3,5,5,6,6,5,5,6,5,6,5,5,4,5,5,5,7,5,5,5,6,5,6,5,4,5,5,6,5,5,5]
        self.assertEqual(sum(durations), 160)
        specs = [
            {"shot_id": f"{i:02}", "frames": duration*24,
             "start_frame": sum(durations[:i-1])*24,
             "end_frame": sum(durations[:i])*24}
            for i, duration in enumerate(durations, 1)
        ]
        plan = {"format": "director_ue_timeline_v1", "project_id": "WaitingOffice",
                "episode_id": "EP01", "fps": 24, "shots": specs,
                "total_frames": 3840}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_file, output_file = root / "plan.json", root / "result.json"
            input_file.write_text(json.dumps(plan))
            with patch.dict(sys.modules, {"unreal": unreal}), patch.dict(
                os.environ, {"DIRECTOR_UE_SPEC_FILE": str(input_file),
                             "DIRECTOR_UE_RESULT_FILE": str(output_file)}
            ):
                script = Path(__file__).resolve().parents[1] / "unreal_build_episode.py"
                load = importlib.util.spec_from_file_location("unreal_build_episode_fake", script)
                module = importlib.util.module_from_spec(load)
                load.loader.exec_module(module)
            result = json.loads(output_file.read_text())
        self.assertTrue(result["ok"])
        self.assertEqual(result["shot_count"], 31)
        self.assertEqual(result["total_frames"], 3840)
        self.assertFalse(result["render_ready"])
        master = assets["/Game/Director/Episodes/WaitingOffice_EP01_Master"]
        sections = master.tracks[0].sections
        self.assertEqual(len(sections), 31)
        self.assertEqual(sections[0].range, (0, 72))
        self.assertEqual(sections[-1].range, (3720, 3840))


if __name__ == "__main__":
    unittest.main()
