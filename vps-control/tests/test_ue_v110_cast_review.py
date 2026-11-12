"""V1.1 authenticated UE cast PNG image bridge + frozen Studio job gate."""
from __future__ import annotations
import binascii
import hashlib
import io
import json
import os
import struct
import sys
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc


def episode(tool,args):
    assert tool=="get_production_episode"
    assert args=={"project_id":"WaitingOffice","episode_id":"EP01"}
    return {"ok":True,"shot_count":31,"shots_truncated":False,
            "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                      "duration_ms":10000 if i==31 else 5000}
                     for i in range(1,32)]}


def characters(tool,args):
    assert tool=="get_project_characters"
    assert args=={"project_id":"WaitingOffice"}
    return {"ok":True,"characters":[
        {"character_id":x,"role":"main"} for x in
        ("CHAR_GPT","CHAR_GEM","CHAR_DS","CHAR_CLA","CHAR_ZERO")
    ]}


def png(w,h):
    def chunk(name,raw):
        return (struct.pack(">I",len(raw))+name+raw+
                struct.pack(">I",binascii.crc32(name+raw)&0xffffffff))
    body=b"".join(b"\0"+b"\xe7\xbc\x9a"*w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"+
            chunk(b"IHDR",struct.pack(">IIBBBBB",w,h,8,2,0,0,0))+
            chunk(b"tEXt",b"Photo\x00"+b"P"*2500)+
            chunk(b"IDAT",zlib.compress(body,6))+chunk(b"IEND",b""))


class MockResponse:
    def __init__(self,url,data,expected_sha=None):
        self.url=url
        self.data=data
        self.headers={
            "Content-Type":"image/png",
            "Content-Length":str(len(data)),
            "X-Director-PNG-SHA256":expected_sha or hashlib.sha256(data).hexdigest(),
        }
    def geturl(self):
        return self.url
    def read(self,size):
        return self.data[:size]
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False


class Opener:
    def __init__(self,data,expected_sha=None):
        self.data=data
        self.expected_sha=expected_sha
    def open(self,request,timeout):
        return MockResponse(request.full_url,self.data,self.expected_sha)


class PreviewTests(unittest.TestCase):
    def test_studio_gate_and_exact_review_task(self):
        requests=[]
        def send(path,method,body,opener,token):
            requests.append((path,method,body))
            return {"ok":True,"job_id":"a"*32,"state":"queued"}
        with patch.dict(os.environ,{"DIRECTOR_UE_WORKER_ENABLED":"1"}),patch.object(
                ue_worker_rpc,"_v2_request",side_effect=send):
            out=ue_worker_rpc.enqueue_ue_cast_review(
                "WaitingOffice","EP01",
                studio_getter=episode,cast_getter=characters)
        self.assertTrue(out["ok"])
        self.assertEqual(len(requests),1)
        path,method,body=requests[0]
        self.assertEqual((path,method),("/v2/jobs","POST"))
        self.assertEqual(body["task"],"render_cast_review_stills")
        self.assertEqual(len(body["shots"]),31)
        self.assertEqual(body["expected_total_ms"],160000)
        self.assertEqual(set(body),{"task","project_id","episode_id",
                                     "fps","shots","expected_total_ms"})

    def test_no_arbitrary_plan_or_wrong_cast(self):
        with patch.object(ue_worker_rpc,"_v2_request") as request:
            out=ue_worker_rpc.enqueue_ue_cast_review(
                "WaitingOffice","EP02",
                cast_getter=lambda *_:self.fail("should not read Studio"))
            self.assertEqual(out["reason"],"cast_review_requires_locked_ep01")
            request.assert_not_called()
            out=ue_worker_rpc.enqueue_ue_cast_review(
                "WaitingOffice","EP01",studio_getter=episode,
                cast_getter=lambda *_:{"ok":True,"characters":[]})
            self.assertEqual(out["reason"],"studio_main_cast_registry_mismatch")
            request.assert_not_called()

    def test_fixed_private_png_route_hash_and_landscape_thumbnail(self):
        raw=png(1280,720)
        job="a"*32
        with patch.dict(os.environ,{"DIRECTOR_UE_WORKER_ENABLED":"1"}),patch.object(
                ue_worker_rpc,"load_token",return_value="f"*64):
            out=ue_worker_rpc.get_ue_cast_review_png(
                job,"LINEUP",opener=Opener(raw))
            self.assertTrue(out["ok"])
            self.assertEqual(out["sha256"],hashlib.sha256(raw).hexdigest())
            self.assertEqual(out["width"],1280)
            derivative=ue_worker_rpc.make_bounded_preview_thumbnail_png(raw)
            self.assertEqual(struct.unpack(">II",derivative[16:24]),(640,360))
            self.assertLess(len(derivative),512*1024)
            self.assertEqual(ue_worker_rpc.get_ue_cast_review_png(
                job,"../../fake",opener=Opener(raw))["reason"],
                "invalid_cast_review_view")
            bad=bytearray(raw)
            bad[-1]^=1
            self.assertEqual(ue_worker_rpc.get_ue_cast_review_png(
                job,"LINEUP",opener=Opener(bytes(bad),hashlib.sha256(raw).hexdigest()))["reason"],
                "cast_review_hash_mismatch")
        # The bridge-safe thumbnail remains RGB/RGBA PNG; it is NOT the
        # original. SHA returned above is for the true UE source image.

    def test_legacy_preview_slots_are_mapped_without_new_plugin_ui(self):
        app=(Path(__file__).resolve().parents[1]/"hub_app.py").read_text("utf-8")
        self.assertIn('mapping={"01":"LINEUP","13":"GPT","26":"DS","31":"ZERO"}',app)
        self.assertIn("get_ue_cast_review_image(job_id: str, view: str)",app)


if __name__=="__main__":
    unittest.main()
