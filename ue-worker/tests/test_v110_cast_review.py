"""V1.1 real image delivery contract, no Unreal process in offline tests."""
from __future__ import annotations
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import agent
import ue_jobs
import ue_previs
import ue_preview_images

VIEWS=("LINEUP","GPT","GEM","DS","CLA","ZERO")
CAST="f32dea96d7a94990b3eb274d1cef3de3"


def plan():
    return {"task":"render_cast_review_stills",
            "project_id":"WaitingOffice","episode_id":"EP01","fps":24,
            "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                      "duration_ms":10000 if i==31 else 5000}
                     for i in range(1,32)],
            "expected_total_ms":160000}


def png(width,height):
    def chunk(kind,body):
        import binascii
        return (struct.pack(">I",len(body))+kind+body+
                struct.pack(">I",binascii.crc32(kind+body)&0xffffffff))
    # 8-bit RGB PNG; lower-case tEXt ancillary chunk ensures >=2 KiB.
    ihdr=struct.pack(">IIBBBBB",width,height,8,2,0,0,0)
    raw=b"".join(b"\x00"+(b"\xff\xdc\xbd" * width) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",ihdr)+
            chunk(b"tEXt",b"OriginalUEUnitTest\x00"+b"A"*2500)+
            chunk(b"IDAT",zlib.compress(raw,6))+chunk(b"IEND",b""))


class FakeJob:
    def __init__(self,root,job,result):
        self.root_factory=lambda:root
        self.job=job
        self.result=result

    def lookup(self,job_id):
        assert job_id==self.job
        return {"state":"succeeded","task":"render_cast_review_stills",
                "project_id":"WaitingOffice","episode_id":"EP01",
                "result":self.result}


class CastReviewTests(unittest.TestCase):
    def test_signed_worker_task_is_frozen_to_one_episode(self):
        result=ue_jobs.sanitized_plan(plan())
        self.assertEqual(result["format"],"director_ue_cast_review_v110")
        self.assertEqual(result["total_frames"],3840)
        self.assertTrue(agent.capabilities()["supports_ep01_cast_review_stills"])
        self.assertIn("render_cast_review_stills",agent.capabilities()["jobs"])
        self.assertFalse(agent.capabilities()["supports_rendering"])
        for field,val in (("project_id","Another"),("episode_id","EP02"),
                          ("fps",30),("expected_total_ms",150000)):
            invalid=plan()
            invalid[field]=val
            with self.assertRaises(ue_jobs.JobError):
                ue_jobs.sanitized_plan(invalid)
        invalid=plan()
        invalid["map"]="/Game/Evil"
        with self.assertRaises(ue_jobs.JobError):
            ue_jobs.sanitized_plan(invalid)

    def test_worker_mrq_six_immutable_receipted_frames(self):
        job="a"*32
        source=(
            Path("Content")/"Director"/"Candidates"/"EP01"/"CastBuilds"
            /("J"+CAST))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source_path=root/source/"Maps"/"EP01_Five_Cast_Review.umap"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(b"KNOWN_SAVED_UNREAL_WORLD")
            for view in ("GPT","GEM","DS","CLA","ZERO"):
                asset=root/source/"Blueprints"/("BP_CHAR_"+view+".uasset")
                asset.parent.mkdir(exist_ok=True)
                asset.write_bytes(b"SAVED_UNREAL_BLUEPRINT")
            sha=hashlib.sha256(source_path.read_bytes()).hexdigest()
            prefix="/Game/Director/Candidates/EP01/ReviewRenders/J"+job
            presets={
                v:prefix+"/Presets/WO_EP01_CastPNG_"+v+".WO_EP01_CastPNG_"+v
                for v in ("wide","portrait")
            }
            seq={
                v:prefix+"/Shots/WO_EP01_CAST_"+v+".WO_EP01_CAST_"+v
                for v in VIEWS
            }

            def fake_ue_run(command,root_arg,log,timeout,env):
                if "-run=pythonscript" in command:
                    data={
                        "ok":True,
                        "source_world":"/Game/Director/Candidates/EP01/CastBuilds/J"+
                                       CAST+"/Maps/EP01_Five_Cast_Review",
                        "review_world":prefix+"/Maps/WO_EP01_CastReview",
                        "cast":{v:"WO_CANDIDATE_CHAR_"+v for v in
                                ("GPT","GEM","DS","CLA","ZERO")},
                        "view_sequences":seq,"mrq_presets":presets,
                        "views":list(VIEWS),"frames_per_view":1,
                        "source_world_unchanged":True,
                    }
                    Path(env["DIRECTOR_UE_RESULT_FILE"]).write_text(
                        json.dumps(data),"utf-8")
                else:
                    name=next(arg for arg in command
                              if arg.startswith("-LevelSequence="))
                    view=name.split("WO_EP01_CAST_")[-1]
                    if view not in VIEWS:
                        raise AssertionError("invalid view "+view)
                    width,height=(1280,720) if view=="LINEUP" else (720,1280)
                    output=Path(env["DIRECTOR_UE_PREVIEW_OUTPUT"])
                    (output/("WO_EP01_CAST_"+view+"_V11_0000.png")).write_bytes(
                        png(width,height))
            work=root/"Jobs"/job
            with patch.object(ue_jobs,"find_editor_cmd",
                    return_value=Path("C:/FakeUnrealEditor-Cmd.exe")),patch.object(
                    ue_previs,"ensure_mrq_plugin",
                    side_effect=lambda p,w:None),patch.object(
                    ue_previs,"_run_unreal",side_effect=fake_ue_run):
                out=ue_previs.render_cast_review(
                    ue_jobs.sanitized_plan(plan()),root,work)
            self.assertEqual(out["preview_count"],6)
            self.assertEqual([a["view"] for a in out["screenshots"]],list(VIEWS))
            self.assertEqual(out["source_cast_sha256"],sha)
            self.assertTrue(out["source_cast_unchanged"])
            self.assertFalse(out["character_masters_approved"])
            self.assertFalse(out["final_film_rendered"])
            self.assertEqual(out["screenshots"][0]["width"],1280)
            fake=FakeJob(root,job,out)
            for view in VIEWS:
                data,digest=ue_preview_images.get_cast_review_png(fake,job,view)
                self.assertEqual(hashlib.sha256(data).hexdigest(),digest)
            self.assertEqual(hashlib.sha256(source_path.read_bytes()).hexdigest(),sha)
            # Changing even 1 byte of a delivered PNG must refuse image retrieval.
            image=(root/"Outputs"/"V11"/job/"Previews"
                   /"WO_EP01_CAST_GPT_V11_0000.png")
            image.write_bytes(image.read_bytes()[:-1]+b"!")
            with self.assertRaisesRegex(ue_jobs.JobError,
                                        "cast_review_png_integrity_failed"):
                ue_preview_images.get_cast_review_png(fake,job,"GPT")

    def test_no_previews_for_unauthorized_or_unfinished_job(self):
        with tempfile.TemporaryDirectory() as td:
            fake=FakeJob(Path(td),"b"*32,{"preview_count":0})
            with self.assertRaises(ue_jobs.JobError):
                ue_preview_images.get_cast_review_png(fake,"b"*32,"LINEUP")
            with self.assertRaises(ue_jobs.JobError):
                ue_preview_images.get_cast_review_png(fake,"b"*32,"EVIL")

    def test_six_actual_unreal_cameras_and_no_fake_art(self):
        source=(ROOT/"unreal_create_previs_preset.py").read_text("utf-8")
        self.assertIn("V11_CAST_SOURCE_JOB = \""+CAST+"\"",source)
        self.assertIn('"LINEUP", "GPT", "GEM", "DS", "CLA", "ZERO"',source)
        self.assertIn("unreal.MovieSceneCameraCutTrack",source)
        self.assertIn("unreal.MoviePipelineImageSequenceOutput_PNG",source)
        self.assertIn("new_level_from_template",source)
        self.assertNotIn("image_gen",source)
        self.assertNotIn("stable_diffusion",source.lower())


if __name__=="__main__":
    unittest.main()
