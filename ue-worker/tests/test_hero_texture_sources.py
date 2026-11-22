"""Offline no-GPU tests for one SHA-pinned post-rig skin-texture candidate."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import ue_jobs
import ue_previs
import ue_process


def spec():
    return ue_jobs.sanitized_plan({
        "task": "build_ep01_hero_texture_sources",
        "project_id": "WaitingOffice", "episode_id": "EP01",
        "fps": 24,
        "shots": [{"shot_id": f"{i:02d}", "ordinal": i,
                   "duration_ms": 10000 if i == 31 else 5000}
                  for i in range(1, 32)],
        "expected_total_ms": 160000,
    })


def source(root):
    project = root / "HeroProjects" / "CHAR_GPT" / "DirectorHeroGPT.uproject"
    project.parent.mkdir(parents=True)
    project.write_text(json.dumps(agent.hero_project_manifest()), encoding="utf-8")
    rig = (project.parent / "Content" / "Director" / "Candidates" /
           "EP01" / "HeroRigs" /
           ("J" + ue_previs.GPT_HERO_RIG_SOURCE_JOB) /
           "MHC_CHAR_GPT_RigV1.uasset")
    rig.parent.mkdir(parents=True)
    rig.write_bytes(b"verified-rig"*8192)
    return project, rig


class HeroTextureTests(unittest.TestCase):
    def test_fixed_plan_and_pinned_rig(self):
        self.assertEqual(spec()["format"], "director_ue_hero_textures_v250")
        self.assertEqual(spec()["total_frames"], 3840)
        self.assertEqual(ue_previs.GPT_HERO_RIG_SOURCE_JOB,
                         "b2a62bb6bc004de4ab747a9de4e3d16d")
        self.assertEqual(ue_previs.GPT_HERO_RIG_SOURCE_SHA256,
                         "78f4b9af93128aed62f0b9d348d758fff7769f292d970982ca80f149befaab24")
        self.assertNotEqual(
            spec()["format"],
            ue_jobs.sanitized_plan({
                "task": "build_ep01_hero_cloud_rig",
                "project_id": "WaitingOffice", "episode_id": "EP01",
                "fps": 24,
                "shots": [{"shot_id": f"{i:02d}", "ordinal": i,
                           "duration_ms": 10000 if i == 31 else 5000}
                          for i in range(1, 32)],
                "expected_total_ms": 160000,
            })["format"])

    def test_sha_drift_blocks_cloud_request_without_work(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, rig = source(root)
            work = root / "Jobs" / ("a"*32)
            with patch.object(ue_process, "run_interactive_hero_rig") as call:
                with self.assertRaisesRegex(ue_jobs.JobError, "hero_texture_rig_hash_drift"):
                    ue_previs.build_gpt_hero_texture_sources(spec(), root, work)
            call.assert_not_called()
            self.assertFalse(work.exists())
            self.assertTrue(rig.is_file())

    def test_positive_receipt_requires_unique_new_native_asset_and_preserves_rig(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project, rig = source(root)
            digest = hashlib.sha256(rig.read_bytes()).hexdigest()
            original = rig.read_bytes()
            work = root / "Jobs" / ("e"*32)

            def fake_run(base, task_work, timeout, task):
                self.assertEqual((base, task_work, timeout, task),
                                 (root, work, 780, "hero_textures_v250"))
                dest = (project.parent / "Content" / "Director" /
                        "Candidates" / "EP01" / "HeroTextures" /
                        ("J" + work.name) / "MHC_CHAR_GPT_TexturesV1.uasset")
                dest.parent.mkdir(parents=True)
                dest.write_bytes(b"native high res textures"*100)
                receipt = {
                    "ok": True, "character_id": "CHAR_GPT",
                    "asset_path": "/Game/Director/Candidates/EP01/HeroTextures/J"+
                                  work.name+"/MHC_CHAR_GPT_TexturesV1",
                    "asset_class": "MetaHumanCharacter",
                    "source_rig_preserved": True, "face_blendshapes_verified": True,
                    "cloud_texture_request_executed": True,
                    "has_high_resolution_textures": True,
                    "groom_ready": False, "wardrobe_ready": False,
                    "cinematic_character_ready": False,
                    "character_master_approved": False,
                }
                (work / "hero_texture_result.json").write_text(
                    json.dumps(receipt), encoding="utf-8")

            with patch.object(ue_previs, "GPT_HERO_RIG_SOURCE_SHA256", digest), \
                 patch.object(ue_process, "run_interactive_hero_rig", side_effect=fake_run):
                result = ue_previs.build_gpt_hero_texture_sources(spec(), root, work)
            self.assertTrue(result["has_high_resolution_textures"])
            self.assertTrue(result["face_blendshapes_verified"])
            self.assertFalse(result["cinematic_character_ready"])
            self.assertFalse(result["character_master_approved"])
            self.assertEqual(rig.read_bytes(), original)

    def test_bad_ticket_task_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            work = root / "Jobs" / ("b"*32)
            with self.assertRaisesRegex(ue_jobs.JobError, "hero_interactive_task_not_allowed"):
                ue_process.run_interactive_hero_rig(
                    root, work, 5, task="user_supplied_arbitrary_script")
            self.assertFalse(work.exists())

    def test_official_cloud_call_and_readback_are_in_source(self):
        source_file = (Path(__file__).resolve().parents[1] /
                       "unreal_create_previs_preset.py").read_text("utf-8")
        code = source_file.split("def hero_texture_sources_main():", 1)[1]
        code = code.split("def hero_cloud_face_rig_main():", 1)[0]
        self.assertIn("MetaHumanCharacterTextureRequestParams()", code)
        self.assertIn("subsystem.request_texture_sources(clone, params)", code)
        self.assertIn('get_editor_property("has_high_resolution_textures")', code)
        self.assertIn('get_editor_property("has_face_dna_blendshapes")', code)
        self.assertIn("save_loaded_asset(clone)", code)
        self.assertIn("remove_object_to_edit(clone)", code)
        self.assertNotIn("subprocess", code)
        self.assertNotIn("os.system", code)
        self.assertNotIn("shell=True", code)


if __name__ == "__main__":
    unittest.main()
