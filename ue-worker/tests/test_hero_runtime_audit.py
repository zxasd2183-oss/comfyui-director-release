"""Read-only real-asset MetaHuman audit job: fixed source and API receipt."""
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
    plan={"task":"audit_ep01_hero_metahuman_runtime",
          "project_id":"WaitingOffice","episode_id":"EP01","fps":24,
          "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                    "duration_ms":10000 if i==31 else 5000}
                   for i in range(1,32)],
          "expected_total_ms":160000}
    return ue_jobs.sanitized_plan(plan)


class HeroAuditTests(unittest.TestCase):
    def test_audit_plan_is_locked(self):
        item=spec()
        self.assertEqual(item["format"],"director_ue_hero_audit_v140")
        self.assertEqual((item["total_frames"],item["total_ms"]),(3840,160000))

    def test_verified_asset_and_no_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            project=root/"HeroProjects"/"CHAR_GPT"/"DirectorHeroGPT.uproject"
            project.parent.mkdir(parents=True)
            project.write_text(json.dumps(agent.hero_project_manifest()),encoding="utf-8")
            seed=ue_previs.GPT_HERO_SOURCE_JOB
            source=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
                    "HeroBuilds"/("J"+seed)/"MHC_CHAR_GPT.uasset")
            source.parent.mkdir(parents=True)
            source.write_bytes(b"native-metahuman-asset")
            work=root/"Jobs"/("b"*32)
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            def fake_runner(command,working_root,log,timeout,env):
                self.assertIn(str(project),command)
                self.assertEqual(env["DIRECTOR_UE_REVIEW_MODE"],"hero_audit_v140")
                result={"ok":True,"asset_path":"/Game/Director/Candidates/EP01/"
                        "HeroBuilds/J"+seed+"/MHC_CHAR_GPT",
                        "asset_class":"MetaHumanCharacter",
                        "source_unmodified":True,"rigged":False,
                        "character_master_approved":False,
                        "costly_cloud_requests_executed":False,
                        "texture_source_state":"absent",
                        "capabilities":{k:True for k in (
                            "character_editor_subsystem","request_auto_rigging",
                            "request_texture_sources","build_meta_human",
                            "try_add_object_to_edit","commit_eyes_settings")},
                        "reference_examples":{k:True for k in (
                            "create","texture","rig","assembly")}}
                Path(env["DIRECTOR_UE_RESULT_FILE"]).write_text(json.dumps(result),
                                                              encoding="utf-8")
            with patch.object(ue_previs,"GPT_HERO_SOURCE_SHA256",digest), \
                 patch.object(ue_jobs,"find_editor_cmd",
                              return_value=Path("UnrealEditor.exe")), \
                 patch.object(ue_previs,"_run_unreal",side_effect=fake_runner):
                outcome=ue_previs.audit_gpt_hero_metahuman_runtime(spec(),root,work)
            self.assertEqual(outcome["seed_asset_sha256"],digest)
            self.assertTrue(outcome["source_unmodified"])
            self.assertFalse(outcome["rigging_done"])
            self.assertEqual(source.read_bytes(),b"native-metahuman-asset")
            with self.assertRaisesRegex(ue_jobs.JobError,"hero_audit_job_collision"):
                with patch.object(ue_previs,"GPT_HERO_SOURCE_SHA256",digest):
                    ue_previs.audit_gpt_hero_metahuman_runtime(spec(),root,work)

    def test_hash_drift_blocks_unreal_launch(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            project=root/"HeroProjects"/"CHAR_GPT"/"DirectorHeroGPT.uproject"
            project.parent.mkdir(parents=True)
            project.write_text(json.dumps(agent.hero_project_manifest()),encoding="utf-8")
            seed=ue_previs.GPT_HERO_SOURCE_JOB
            source=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
                    "HeroBuilds"/("J"+seed)/"MHC_CHAR_GPT.uasset")
            source.parent.mkdir(parents=True)
            source.write_bytes(b"tampered")
            work=root/"Jobs"/("c"*32)
            with patch.object(ue_previs,"_run_unreal") as runner:
                with self.assertRaisesRegex(ue_jobs.JobError,"hero_audit_source_hash_drift"):
                    ue_previs.audit_gpt_hero_metahuman_runtime(spec(),root,work)
            runner.assert_not_called()
            self.assertFalse(work.exists())


if __name__=="__main__":
    unittest.main()
