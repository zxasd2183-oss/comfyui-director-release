"""Real MetaHuman iris pass contract and source non-overwrite guarantees."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import agent
import ue_jobs
import ue_previs


def spec():
    return ue_jobs.sanitized_plan({
        "task":"build_ep01_hero_amber_eyes",
        "project_id":"WaitingOffice","episode_id":"EP01","fps":24,
        "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                  "duration_ms":10000 if i==31 else 5000}
                 for i in range(1,32)],
        "expected_total_ms":160000})


class EyesTest(unittest.TestCase):
    def test_task_is_fixed_to_one_original_ep01(self):
        x=spec()
        self.assertEqual(x["format"],"director_ue_hero_eyes_v150")
        self.assertEqual(x["total_frames"],3840)

    def test_eyes_candidate_requires_real_unmodified_source(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            project=root/"HeroProjects"/"CHAR_GPT"/"DirectorHeroGPT.uproject"
            project.parent.mkdir(parents=True)
            project.write_text(json.dumps(agent.hero_project_manifest()),encoding="utf-8")
            source=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
                    "HeroBuilds"/("J"+ue_previs.GPT_HERO_SOURCE_JOB)/
                    "MHC_CHAR_GPT.uasset")
            source.parent.mkdir(parents=True)
            source.write_bytes(b"real_native_meta_seed")
            old_hash=hashlib.sha256(source.read_bytes()).hexdigest()
            work=root/"Jobs"/("c"*32)
            def run_ue(command,r,log,timeout,env):
                self.assertIn(str(project),command)
                self.assertEqual(env["DIRECTOR_UE_REVIEW_MODE"],"hero_eyes_v150")
                dest=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
                      "HeroLooks"/("J"+work.name)/"MHC_CHAR_GPT_AmberV1.uasset")
                dest.parent.mkdir(parents=True)
                dest.write_bytes(b"edited_native_iris"*100)
                obj={"ok":True,"asset_path":"/Game/Director/Candidates/EP01/"
                     "HeroLooks/J"+work.name+"/MHC_CHAR_GPT_AmberV1",
                     "asset_class":"MetaHumanCharacter",
                     "eye_tint_linear":[0.85,0.55,0.25,1.0],
                     "eye_saturation":1.25,
                     "both_eyes_readback_verified":True,
                     "original_asset_untouched":True,
                     "groom_applied":False,"wardrobe_applied":False,
                     "face_rig_created":False,"cinematic_character_ready":False,
                     "character_master_approved":False}
                Path(env["DIRECTOR_UE_RESULT_FILE"]).write_text(
                    json.dumps(obj),encoding="utf-8")
            with patch.object(ue_previs,"GPT_HERO_SOURCE_SHA256",old_hash), \
                 patch.object(ue_jobs,"find_editor_cmd",
                              return_value=Path("UnrealEditor.exe")), \
                 patch.object(ue_previs,"_run_unreal",side_effect=run_ue):
                result=ue_previs.build_gpt_hero_amber_eyes(spec(),root,work)
            self.assertTrue(result["both_eye_parameters_verified"])
            self.assertFalse(result["creative_eye_color_visual_approved"])
            self.assertFalse(result["cinematic_character_ready"])
            self.assertEqual(source.read_bytes(),b"real_native_meta_seed")
            self.assertTrue(result["candidate_uasset_sha256"])

    def test_source_hash_drift_blocks_editor(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            project=root/"HeroProjects"/"CHAR_GPT"/"DirectorHeroGPT.uproject"
            project.parent.mkdir(parents=True)
            project.write_text(json.dumps(agent.hero_project_manifest()),encoding="utf-8")
            source=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
                    "HeroBuilds"/("J"+ue_previs.GPT_HERO_SOURCE_JOB)/
                    "MHC_CHAR_GPT.uasset")
            source.parent.mkdir(parents=True)
            source.write_bytes(b"tampered")
            work=root/"Jobs"/("f"*32)
            with patch.object(ue_previs,"_run_unreal") as runner:
                with self.assertRaisesRegex(ue_jobs.JobError,
                                             "hero_eyes_original_hash_changed"):
                    ue_previs.build_gpt_hero_amber_eyes(spec(),root,work)
            runner.assert_not_called()
            self.assertFalse(work.exists())


if __name__=="__main__":
    unittest.main()
