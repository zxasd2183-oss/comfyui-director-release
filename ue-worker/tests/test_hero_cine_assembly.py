"""No-GPU tests for the isolated, real UE Cine MetaHuman assembly gate."""
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
import ue_process
import ue_previs


def plan():
    return ue_jobs.sanitized_plan({
        "task": "build_ep01_hero_cine_assembly",
        "project_id": "WaitingOffice", "episode_id": "EP01", "fps": 24,
        "shots": [{"shot_id": f"{i:02d}", "ordinal": i,
                   "duration_ms": 10000 if i == 31 else 5000}
                  for i in range(1, 32)],
        "expected_total_ms": 160000,
    })


def source(root):
    project = root / "HeroProjects" / "CHAR_GPT" / "DirectorHeroGPT.uproject"
    project.parent.mkdir(parents=True)
    project.write_text(json.dumps(agent.hero_project_manifest()), "utf-8")
    asset = (project.parent / "Content" / "Director" / "Candidates" / "EP01" /
             "HeroTextures" / ("J" + ue_previs.GPT_HERO_TEXTURE_SOURCE_JOB) /
             "MHC_CHAR_GPT_TexturesV1.uasset")
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"native-textured-face-rig" * 4096)
    return project, asset


class HeroCineTests(unittest.TestCase):
    def test_fixed_identity_and_source_digest(self):
        self.assertEqual(plan()["format"], "director_ue_hero_cine_v260")
        self.assertEqual((plan()["total_frames"], plan()["total_ms"]), (3840, 160000))
        self.assertEqual(ue_previs.GPT_HERO_TEXTURE_SOURCE_JOB,
                         "be13a12e3f2246c894d377ad12c19ae0")
        self.assertEqual(ue_previs.GPT_HERO_TEXTURE_SOURCE_SHA256,
                         "aaacb49c72bcbd0f37aa22df974d2765298eaf0277b5f6b795583616c262904f")

    def test_drift_refuses_job_before_editor_call(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, asset = source(root)
            work = root / "Jobs" / ("a" * 32)
            with patch.object(ue_process, "run_interactive_hero_rig") as launch:
                with self.assertRaisesRegex(ue_jobs.JobError, "hero_cine_source_hash_drift"):
                    ue_previs.build_gpt_hero_cine_assembly(plan(), root, work)
            self.assertFalse(work.exists())
            launch.assert_not_called()
            self.assertTrue(asset.is_file())

    def test_success_requires_native_blueprint_and_two_skeletal_meshes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project, source_asset = source(root)
            before = source_asset.read_bytes()
            digest = hashlib.sha256(before).hexdigest()
            work = root / "Jobs" / ("b" * 32)
            folder = (project.parent / "Content" / "Director" / "Candidates" /
                      "EP01" / "HeroCine" / ("J" + work.name))
            base = "/Game/Director/Candidates/EP01/HeroCine/J" + work.name
            names = [
                ("Build/CHAR_GPT_Cine/BP_CHAR_GPT_Cine", "Blueprint"),
                ("Build/CHAR_GPT_Cine/Face/SKM_Face", "SkeletalMesh"),
                ("Build/CHAR_GPT_Cine/Body/SKM_Body", "SkeletalMesh"),
            ]

            def execute(given_root, given_work, timeout, task):
                self.assertEqual((given_root, given_work, timeout, task),
                                 (root, work, 780, "hero_cine_v260"))
                target = folder / "MHC_CHAR_GPT_CineV1.uasset"
                target.parent.mkdir(parents=True)
                target.write_bytes(b"fresh-cine-asset" * 128)
                for rel, _ in names:
                    f = folder / (rel + ".uasset")
                    f.parent.mkdir(parents=True)
                    f.write_bytes((rel.encode("ascii") + b"x") * 128)
                payload = {
                    "ok": True, "character_id": "CHAR_GPT",
                    "asset_path": base + "/MHC_CHAR_GPT_CineV1",
                    "pipeline_type": "CINEMATIC",
                    "source_unchanged": True,
                    "face_blendshapes_verified": True,
                    "has_high_resolution_textures": True,
                    "build_executed": True,
                    "total_assets": len(names),
                    "asset_manifest": [
                        {"asset_path": base + "/" + rel, "asset_class": kind}
                        for rel, kind in names
                    ],
                    "wardrobe_ready": False,
                    "groom_ready": False,
                    "cinematic_character_ready": False,
                    "character_master_approved": False,
                }
                (work / "hero_cine_result.json").write_text(
                    json.dumps(payload), encoding="utf-8")

            with patch.object(ue_previs, "GPT_HERO_TEXTURE_SOURCE_SHA256", digest), \
                 patch.object(ue_process, "run_interactive_hero_rig", side_effect=execute):
                result = ue_previs.build_gpt_hero_cine_assembly(plan(), root, work)
            self.assertEqual(result["pipeline_type"], "CINEMATIC")
            self.assertEqual(len(result["verified_key_assets"]), 3)
            self.assertFalse(result["cinematic_character_ready"])
            self.assertEqual(source_asset.read_bytes(), before)

    def test_script_uses_official_api_only_and_never_approves(self):
        source_code = (Path(__file__).resolve().parents[1] /
                       "unreal_create_previs_preset.py").read_text("utf-8")
        fragment = source_code.split("def hero_cine_assembly_main():", 1)[1].split(
            "def hero_texture_sources_main():", 1)[0]
        self.assertIn("MetaHumanCharacterEditorBuildParameters()", fragment)
        self.assertIn("MetaHumanDefaultPipelineType.CINEMATIC", fragment)
        self.assertIn("subsystem.can_build_meta_human(clone, True)", fragment)
        self.assertIn("subsystem.build_meta_human(clone, params)", fragment)
        self.assertIn("save_directory(", fragment)
        self.assertIn("asset_class_path.asset_name", fragment)
        self.assertIn('"character_master_approved": False', fragment)
        self.assertNotIn("subprocess", fragment)
        self.assertNotIn("os.system", fragment)
        self.assertNotIn("shell=True", fragment)
        runner_source = (Path(__file__).resolve().parents[1] /
                         "ue_process.py").read_text("utf-8")
        self.assertIn("hero_cine_interactive_runner_upgrade_required", runner_source)
        self.assertIn("_bridge_signal_cancel(folder, ident)", runner_source)


if __name__ == "__main__":
    unittest.main()
