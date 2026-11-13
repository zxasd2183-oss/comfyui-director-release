"""Isolated actual MetaHuman face-contour dispatch and source SHA contracts."""
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


def studio_spec():
    return ue_jobs.sanitized_plan({
        "task":"build_ep01_hero_face_contour",
        "project_id":"WaitingOffice","episode_id":"EP01","fps":24,
        "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                  "duration_ms":10000 if i==31 else 5000}
                 for i in range(1,32)],
        "expected_total_ms":160000,
    })


def setup_sources(root):
    project=root/"HeroProjects"/"CHAR_GPT"/"DirectorHeroGPT.uproject"
    project.parent.mkdir(parents=True)
    project.write_text(json.dumps(agent.hero_project_manifest()),encoding="utf-8")
    amber=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
           "HeroLooks"/("J"+ue_previs.GPT_HERO_AMBER_SOURCE_JOB)/
           "MHC_CHAR_GPT_AmberV1.uasset")
    seed=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
          "HeroBuilds"/("J"+ue_previs.GPT_HERO_SOURCE_JOB)/
          "MHC_CHAR_GPT.uasset")
    for source,data in ((amber,b"edited-gpt-amber-seed"*60),
                        (seed,b"original-gpt-seed"*60)):
        source.parent.mkdir(parents=True)
        source.write_bytes(data)
    return project,amber,seed


class FaceContourTests(unittest.TestCase):
    def test_plan_fixed_to_only_gpt_episode(self):
        p=studio_spec()
        self.assertEqual(p["format"],"director_ue_hero_face_v170")
        self.assertEqual((p["total_frames"],p["total_ms"]),(3840,160000))

    def test_cloned_native_face_candidate_and_original_sources_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            project,amber,seed=setup_sources(root)
            work=root/"Jobs"/("a"*32)
            before_amber=amber.read_bytes()
            before_seed=seed.read_bytes()
            def fake_runner(argv,root_arg,log,timeout,env):
                self.assertIn(str(project),argv)
                self.assertEqual(env["DIRECTOR_UE_REVIEW_MODE"],"hero_face_v170")
                self.assertEqual(timeout,720)
                dest=(project.parent/"Content"/"Director"/"Candidates"/
                      "EP01"/"HeroFaces"/("J"+work.name)/
                      "MHC_CHAR_GPT_FaceContourV1.uasset")
                dest.parent.mkdir(parents=True)
                dest.write_bytes(b"native-metahuman-face-sculpt"*68)
                result={
                    "ok":True,"character_id":"CHAR_GPT",
                    "asset_path":"/Game/Director/Candidates/EP01/HeroFaces/J"+
                                 work.name+"/MHC_CHAR_GPT_FaceContourV1",
                    "asset_class":"MetaHumanCharacter",
                    "face_edit_api":"translate_face_landmarks_commit_face_state",
                    "landmark_count":200,"landmarks_selected":18,
                    "live_landmarks_changed":15,"max_lateral_delta_cm":0.10,
                    "jaw_style":"subtle_symmetric_lower_face_narrowing_v1",
                    "real_ue_sculpt_committed":True,
                    "original_asset_untouched":True,
                    "cloud_requests_executed":False,
                    "rigging_done":False,"high_res_textures_downloaded":False,
                    "groom_applied":False,"wardrobe_applied":False,
                    "cinematic_character_ready":False,
                    "character_master_approved":False,"visual_approved":False,
                }
                Path(env["DIRECTOR_UE_RESULT_FILE"]).write_text(json.dumps(result),
                                                              encoding="utf-8")
            with patch.object(ue_previs,"GPT_HERO_AMBER_SOURCE_SHA256",
                              hashlib.sha256(before_amber).hexdigest()), \
                 patch.object(ue_previs,"GPT_HERO_SOURCE_SHA256",
                              hashlib.sha256(before_seed).hexdigest()), \
                 patch.object(ue_jobs,"find_editor_cmd",
                              return_value=Path("UnrealEditor.exe")), \
                 patch.object(ue_previs,"_run_unreal",side_effect=fake_runner):
                receipt=ue_previs.build_gpt_hero_face_contour(studio_spec(),root,work)
            self.assertEqual(receipt["live_landmarks_changed"],15)
            self.assertTrue(receipt["real_ue_face_edit_committed"])
            self.assertFalse(receipt["creative_face_visual_approved"])
            self.assertFalse(receipt["full_face_rig_ready"])
            self.assertEqual(amber.read_bytes(),before_amber)
            self.assertEqual(seed.read_bytes(),before_seed)
            self.assertNotEqual(receipt["candidate_uasset_sha256"],
                                hashlib.sha256(before_amber).hexdigest())

    def test_tampered_parent_blocks_editor_before_any_work(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            project,amber,seed=setup_sources(root)
            work=root/"Jobs"/("c"*32)
            with patch.object(ue_previs,"_run_unreal") as execute:
                with self.assertRaisesRegex(ue_jobs.JobError,
                                             "hero_face_source_hash_drift"):
                    ue_previs.build_gpt_hero_face_contour(studio_spec(),root,work)
            execute.assert_not_called()
            self.assertFalse(work.exists())


if __name__=="__main__":
    unittest.main()
