"""GPU clip return HTTP client: isolated fake Studio, no external requests."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio_return_client import read_token_file, return_shot, ReturnClientError


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.cred=self.root/"return.token"
        self.cred.write_text("X"*64)
        self.cred.chmod(0o600)
        self.plan={"studio_handoff":{
            "project_id":"WaitingOffice","episode_id":"EP01","shot_id":"01",
            "video_revision":3,"package_sha256":"a"*64}}
        self.folder=self.root/"results"/"01"
        self.folder.mkdir(parents=True)
        self.movie=self.folder/"one.mp4"
        self.movie.write_bytes(b"\x00\x00\x00\x18ftypisom"+b"Z"*768)
        self.bytes=self.movie.stat().st_size
        self.sha=hashlib.sha256(self.movie.read_bytes()).hexdigest()
        (self.folder/"manifest.json").write_text(json.dumps({
            "shot_id":"01","prompt_id":"abc-123","downloaded":[{
                "file":"one.mp4","sha256":self.sha,"bytes":self.bytes}]}))

    def test_token_requires_private_0600_file(self):
        self.assertEqual(read_token_file(self.cred),"X"*64)
        self.cred.chmod(0o644)
        with self.assertRaisesRegex(ReturnClientError,"0600"):
            read_token_file(self.cred)

    def test_uploads_owner_scoped_clip_and_chunks(self):
        calls=[]
        def api(command,body,token):
            calls.append((command,body))
            self.assertEqual(token,"X"*64)
            if command=="start":
                self.assertEqual(body["package_sha256"],"a"*64)
                self.assertEqual(body["plan_revision"],3)
                return {"ok":True,"upload_id":"UP_"+"f"*32,"received_bytes":0}
            if command=="chunk":
                self.assertEqual(body["offset"],0)
                import base64
                self.assertEqual(base64.b64decode(body["chunk_base64"]),
                                 self.movie.read_bytes())
                return {"ok":True,"received_bytes":self.bytes}
            if command=="finish":
                return {"ok":True,"take_id":"TAKE_"+"f"*32,"status":"in_review"}
            raise AssertionError(command)
        result=return_shot(self.plan,self.root/"results","01","X"*64,sender=api)
        self.assertEqual(result["status"],"in_review")
        self.assertEqual([a for a,_ in calls],["start","chunk","finish"])

    def test_resume_and_existing_take_skip_duplicate_bytes(self):
        uploaded=[]
        def sender(command,data,token):
            uploaded.append(command)
            return {"ok":True,"already_imported":True,"take_id":"TAKE_"+"f"*32}
        self.assertTrue(return_shot(self.plan,self.root/"results","01","X"*64,
                                    sender=sender)["already_imported"])
        self.assertEqual(uploaded,["start"])

    def test_corrupt_or_unpinned_video_never_uploads(self):
        self.movie.write_bytes(b"corrupted")
        with self.assertRaisesRegex(ReturnClientError,"size outside Studio limits"):
            return_shot(self.plan,self.root/"results","01","X"*64,
                        sender=lambda *args: self.fail("Not allowed"))
        self.movie.write_bytes(b"Z"*512)
        with self.assertRaisesRegex(ReturnClientError,"integrity mismatch"):
            return_shot(self.plan,self.root/"results","01","X"*64,
                        sender=lambda *args: self.fail("Not allowed"))
        self.plan.pop("studio_handoff")
        with self.assertRaisesRegex(ReturnClientError,"receipts missing"):
            return_shot(self.plan,self.root/"results","01","X"*64,
                        sender=lambda *args: self.fail("Not allowed"))


if __name__=="__main__":
    unittest.main()
