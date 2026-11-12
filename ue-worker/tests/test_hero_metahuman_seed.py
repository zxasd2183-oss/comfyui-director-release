"""Verify real uasset receipt, isolated project, strict source preservation."""
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


def fixed_plan():
    return {"task":"build_ep01_hero_metahuman_seed",
            "project_id":"WaitingOffice","episode_id":"EP01","fps":24,
            "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                      "duration_ms":10000 if i==31 else 5000}
                     for i in range(1,32)],
            "expected_total_ms":160000}


class HeroMetaHumanSeedTests(unittest.TestCase):
    def test_fixed_spec_and_no_arbitrary_inputs(self):
        spec=ue_jobs.sanitized_plan(fixed_plan())
        self.assertEqual(spec["format"],"director_ue_hero_seed_v130")
        self.assertEqual((spec["total_ms"],spec["total_frames"]),(160000,3840))
        corrupt=fixed_plan()
        corrupt["project_path"]="C:/Users/random/"
        with self.assertRaisesRegex(ue_jobs.JobError,"invalid_fields"):
            ue_jobs.sanitized_plan(corrupt)

    def test_native_asset_receipt_requires_real_uasset(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            original=root/"DirectorVirtualStudio.uproject"
            original.write_bytes(b"FROZEN EP01")
            project=root/"HeroProjects"/"CHAR_GPT"/"DirectorHeroGPT.uproject"
            project.parent.mkdir(parents=True)
            project.write_text(json.dumps(agent.hero_project_manifest()),encoding="utf-8")
            work=root/"Jobs"/("a"*32)
            seed=ue_jobs.sanitized_plan(fixed_plan())
            def emulate_unreal(command,root_arg,log,timeout,env):
                self.assertIn(str(project),command)
                self.assertEqual(env["DIRECTOR_UE_REVIEW_MODE"],"hero_seed_v130")
                asset=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
                       "HeroBuilds"/("J"+work.name)/"MHC_CHAR_GPT.uasset")
                asset.parent.mkdir(parents=True)
                asset.write_bytes(b"native-uasset-test"*130)
                result={
                    "ok":True,"kind":"real_native_metahuman_character_seed_v130",
                    "asset_path":"/Game/Director/Candidates/EP01/HeroBuilds/J"+
                                 work.name+"/MHC_CHAR_GPT",
                    "asset_class":"MetaHumanCharacter",
                    "project":"DirectorHeroGPT",
                    "independent_ep01_source_untouched":True,
                    "rigging_done":False,"textures_downloaded":False,
                    "groom_applied":False,"wardrobe_applied":False,
                    "character_master_approved":False,
                    "cinematic_character_ready":False,
                }
                Path(env["DIRECTOR_UE_RESULT_FILE"]).write_text(json.dumps(result),
                                                               encoding="utf-8")
            with patch.object(ue_jobs,"find_editor_cmd",
                              return_value=root/"UnrealEditor-Cmd.exe"), \
                 patch.object(ue_previs,"_run_unreal",side_effect=emulate_unreal):
                receipt=ue_previs.build_gpt_hero_metahuman_seed(seed,root,work)
            self.assertEqual(receipt["character_id"],"CHAR_GPT")
            self.assertTrue(receipt["native_uasset_verified"])
            self.assertFalse(receipt["cinematic_character_ready"])
            self.assertFalse(receipt["character_master_approved"])
            self.assertEqual(original.read_bytes(),b"FROZEN EP01")
            with self.assertRaisesRegex(ue_jobs.JobError,"hero_seed_job_collision"):
                ue_previs.build_gpt_hero_metahuman_seed(seed,root,work)

    def test_missing_project_blocks_before_editor_run(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            work=root/"Jobs"/("b"*32)
            with patch.object(ue_previs,"_run_unreal") as exec_:
                with self.assertRaisesRegex(ue_jobs.JobError,
                                             "hero_isolated_project_missing"):
                    ue_previs.build_gpt_hero_metahuman_seed(
                        ue_jobs.sanitized_plan(fixed_plan()),root,work)
            exec_.assert_not_called()
            self.assertFalse(work.exists())


if __name__=="__main__":
    unittest.main()
