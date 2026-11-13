"""Strict one-shot MetaHuman Cloud rig gate for source-pinned EP01 hero."""
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
        "task":"build_ep01_hero_cloud_rig","project_id":"WaitingOffice",
        "episode_id":"EP01","fps":24,
        "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                  "duration_ms":10000 if i==31 else 5000}
                 for i in range(1,32)],"expected_total_ms":160000})


def sources(root):
    project=root/"HeroProjects"/"CHAR_GPT"/"DirectorHeroGPT.uproject"
    project.parent.mkdir(parents=True)
    project.write_text(json.dumps(agent.hero_project_manifest()),encoding="utf-8")
    files=(
        ("HeroFaces",ue_previs.GPT_HERO_FACE_SOURCE_JOB,
         "MHC_CHAR_GPT_FaceContourV1.uasset",b"face"*8192),
        ("HeroLooks",ue_previs.GPT_HERO_AMBER_SOURCE_JOB,
         "MHC_CHAR_GPT_AmberV1.uasset",b"eyes"*1024),
        ("HeroBuilds",ue_previs.GPT_HERO_SOURCE_JOB,
         "MHC_CHAR_GPT.uasset",b"seed"*1024),
    )
    res=[]
    for folder,job,name,data in files:
        f=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
           folder/("J"+job)/name)
        f.parent.mkdir(parents=True)
        f.write_bytes(data)
        res.append(f)
    return project,res


class CloudRigTests(unittest.TestCase):
    def test_manifest_is_frozen(self):
        p=spec()
        self.assertEqual(p["format"],"director_ue_hero_rig_v200")
        self.assertEqual((p["total_frames"],p["total_ms"]),(3840,160000))

    def test_rig_candidate_saves_only_to_job_folder(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            project,items=sources(root)
            digests=[hashlib.sha256(p.read_bytes()).hexdigest() for p in items]
            work=root/"Jobs"/("d"*32)
            def run(argv,r,log,timeout,env):
                self.assertEqual(env["DIRECTOR_UE_REVIEW_MODE"],"hero_rig_v200")
                self.assertEqual(timeout,780)
                self.assertIn(str(project),argv)
                dest=(project.parent/"Content"/"Director"/"Candidates"/"EP01"/
                      "HeroRigs"/("J"+work.name)/"MHC_CHAR_GPT_RigV1.uasset")
                dest.parent.mkdir(parents=True)
                dest.write_bytes(b"native-rigged-face-joints-blendshapes"*90)
                data={
                    "ok":True,"character_id":"CHAR_GPT",
                    "asset_path":"/Game/Director/Candidates/EP01/HeroRigs/J"+
                        work.name+"/MHC_CHAR_GPT_RigV1",
                    "asset_class":"MetaHumanCharacter",
                    "rig_type":"JOINTS_AND_BLEND_SHAPES",
                    "full_face_rig_verified":True,
                    "cloud_auto_rig_request_executed":True,
                    "texture_request_executed":False,
                    "source_asset_preserved":True,
                    "full_texture_sources_ready":False,
                    "hair_ready":False,"wardrobe_ready":False,
                    "cinematic_character_ready":False,
                    "character_master_approved":False,
                }
                Path(env["DIRECTOR_UE_RESULT_FILE"]).write_text(json.dumps(data),
                                                                  encoding="utf-8")
            with patch.object(ue_previs,"GPT_HERO_FACE_SOURCE_SHA256",digests[0]), \
                 patch.object(ue_previs,"GPT_HERO_AMBER_SOURCE_SHA256",digests[1]), \
                 patch.object(ue_previs,"GPT_HERO_SOURCE_SHA256",digests[2]), \
                 patch.object(ue_jobs,"find_editor_cmd",
                              return_value=Path("UnrealEditor.exe")), \
                 patch.object(ue_previs,"_run_unreal",side_effect=run):
                result=ue_previs.build_gpt_hero_cloud_rig(spec(),root,work)
            self.assertTrue(result["full_face_rig_verified"])
            self.assertFalse(result["texture_sources_ready"])
            self.assertFalse(result["character_master_approved"])
            self.assertEqual([hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in items],digests)

    def test_source_hash_drift_blocks_cloud_before_start(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            _,items=sources(root)
            work=root/"Jobs"/("e"*32)
            with patch.object(ue_previs,"_run_unreal") as run:
                with self.assertRaisesRegex(ue_jobs.JobError,
                                             "hero_rig_source_hash_changed"):
                    ue_previs.build_gpt_hero_cloud_rig(spec(),root,work)
            run.assert_not_called()
            self.assertFalse(work.exists())

    def test_cloud_script_uses_no_injected_commands_or_secrets(self):
        src=(Path(__file__).resolve().parents[1]/
             "unreal_create_previs_preset.py").read_text("utf-8")
        begin=src.index("def hero_cloud_face_rig_main():")
        end=src.index('if os.environ.get("DIRECTOR_UE_REVIEW_MODE") == "hero_rig_v200":')
        code=src[begin:end]
        self.assertIn("MetaHumanRigType.JOINTS_AND_BLEND_SHAPES",code)
        self.assertIn("params.blocking=True",code)
        self.assertIn('get_editor_property("has_face_dna_blendshapes")',code)
        self.assertIn("subsystem.request_auto_rigging(clone,params)",code)
        self.assertIn('subsystem.remove_object_to_edit(clone)',code)
        self.assertNotIn("request_texture_sources",code)
        self.assertNotIn("os.system(",code)
        self.assertNotIn("subprocess",code)


if __name__=="__main__":
    unittest.main()
