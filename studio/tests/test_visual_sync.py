"""Authenticated private Hub -> Studio image sync; no GPU dependencies."""
import base64
import hashlib
import http.client
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import json
import secrets
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_server as server
import studio_brain as brain
import production_core as prod
import visual_library as visuals

PNG=bytes.fromhex(
  "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
  "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")
SECRET=b"t"*32
PATH="/api/v1/brain/visual"


class HubVisualSyncHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app=server.StudioServer(str(Path(self.temp.name)/"studio.sqlite"),
            poller=server.Poller(probe=lambda tool:{"ok":False,"reason":"offline"}),
            bind=("127.0.0.1",0))
        self.app.brain_auth=brain.BrainAuthenticator(SECRET)
        with closing(prod.open_db(self.app.production_db_path)) as db:
            prod.create_project(db,"WaitingOffice","待回答事务所")
            prod.create_episode(db,"WaitingOffice","EP01","第一集",1)
            prod.create_shot(db,"WaitingOffice","EP01","01",1,3000)
            db.execute("INSERT INTO episode_outlines "
                "(project_id,episode_id,revision,outline_sha256,body,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                ("WaitingOffice","EP01",1,hashlib.sha256(b"V1 preserved").hexdigest(),
                 "V1 preserved",int(time.time())))
        self.thread=threading.Thread(target=self.app.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.app.shutdown();self.app.server_close();self.thread.join(3)

    def make_call(self,body,signed=True,changes=None,nonce=None):
        payload=json.dumps(body).encode("utf-8")
        stamp=str(int(time.time()))
        nonce=nonce or secrets.token_hex(16)
        headers={"Host":"127.0.0.1:8900","Content-Type":"application/json",
                 "X-Director-Brain-Time":stamp,"X-Director-Brain-Nonce":nonce,
                 "X-Director-Brain-Signature":brain.signature(
                     SECRET,"POST",PATH,stamp,nonce,payload) if signed else "0"*64}
        headers.update(changes or {})
        conn=http.client.HTTPConnection("127.0.0.1",self.app.server_port,timeout=8)
        conn.request("POST",PATH,payload,headers)
        res=conn.getresponse()
        data=res.read()
        status=res.status
        conn.close()
        return status,json.loads(data)

    def body(self,source="file_00000abcde123456"):
        return {"project_id":"WaitingOffice","episode_id":"EP01",
            "kind":"character","subject_id":"CHAR_GEM","filename":"Gemini.png",
            "source_file_id":source,
            "image_base64":base64.b64encode(PNG).decode()}

    def test_signed_sync_idempotent_existing_shot_and_v1_unchanged(self):
        code,a=self.make_call(self.body())
        self.assertEqual(code,201,a)
        self.assertFalse(a["gpu_action"])
        first=a["visual_id"]
        code,b=self.make_call(self.body())
        self.assertEqual(code,200,b)
        self.assertEqual(b["visual_id"],first)
        self.assertTrue(b["unchanged"])
        with closing(prod.open_db(self.app.production_db_path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_import_sources").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM production_shots").fetchone()[0],1)
            row=db.execute("SELECT body,revision FROM episode_outlines").fetchone()
            self.assertEqual(tuple(row),("V1 preserved",1))
            self.assertTrue(prod.verify_chain(db))

    def test_concurrent_same_file_only_one_visual_and_source(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.make_call(self.body()),range(4)))
        self.assertEqual(sorted(code for code,_ in results),[200,200,200,201])
        ids={result["visual_id"] for _,result in results}
        self.assertEqual(len(ids),1)
        with closing(prod.open_db(self.app.production_db_path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_import_sources").fetchone()[0],1)
            self.assertTrue(prod.verify_chain(db))

    def test_original_image_can_be_read_back_through_brain_episode(self):
        code,out=self.make_call(self.body())
        self.assertEqual(code,201,out)
        detail=brain.execute(self.app.production_db_path,"get_production_episode",
                             {"project_id":"WaitingOffice","episode_id":"EP01"})
        self.assertEqual(detail["visual_count"],1)
        self.assertEqual(detail["visuals"][0]["visual_id"],out["visual_id"])
        self.assertEqual(detail["visuals"][0]["source"],"ChatGPT")
        self.assertEqual(detail["visuals"][0]["subject_id"],"CHAR_GEM")
        self.assertEqual(visuals.read_visual(
            self.app.production_db_path,"WaitingOffice","EP01",
            out["visual_id"])[1],PNG)
        # Legacy production asset count and V1 outline remain independent.
        self.assertEqual(detail["assets"],[])
        self.assertEqual(detail["outline"]["body"],"V1 preserved")

    def test_atomic_failure_leaves_no_asset_provenance_or_file(self):
        from visual_library import _audit as original_audit
        def fail_second_event(db,actor,action,target,data):
            if action=="visual.source_linked":
                raise RuntimeError("simulated_mid_transaction_failure")
            return original_audit(db,actor,action,target,data)
        with patch.object(visuals,"_audit",side_effect=fail_second_event):
            with self.assertRaises(RuntimeError):
                visuals.ingest_chatgpt_image(
                    self.app.production_db_path,self.body(),actor="test")
        with closing(prod.open_db(self.app.production_db_path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_import_sources").fetchone()[0],0)
            self.assertTrue(prod.verify_chain(db))
        media_path=Path(self.app.production_db_path).parent/"visual_media"
        self.assertEqual(list(media_path.glob("*")),[])

    def test_same_source_with_changed_bytes_is_rejected(self):
        code,_=self.make_call(self.body())
        self.assertEqual(code,201)
        changed=self.body()
        raw=bytearray(PNG)
        raw[-2]^=1
        changed["image_base64"]=base64.b64encode(bytes(raw)).decode()
        status,result=self.make_call(changed)
        self.assertEqual(status,409)
        self.assertEqual(result["reason"],"source_file_integrity_conflict")

    def test_bad_signature_and_forwarded_proxy_blocked(self):
        code,_=self.make_call(self.body(),signed=False)
        self.assertEqual(code,403)
        code,_=self.make_call(self.body(),changes={"X-Forwarded-Proto":"https"})
        self.assertEqual(code,403)
        code,_=self.make_call(self.body(),changes={"Origin":"https://evil.example"})
        self.assertEqual(code,403)
        with closing(prod.open_db(self.app.production_db_path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],0)

    def test_cross_episode_and_invalid_image_rejected(self):
        data=self.body()
        data["episode_id"]="EP99"
        code,_=self.make_call(data)
        self.assertEqual(code,404)
        data=self.body()
        data["image_base64"]=base64.b64encode(b"not image"*10).decode()
        code,result=self.make_call(data)
        self.assertEqual(code,415,result)
        with closing(prod.open_db(self.app.production_db_path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],0)

    def test_replay_nonce_cannot_upload_twice(self):
        nonce="f"*32
        code,_=self.make_call(self.body(),nonce=nonce)
        self.assertEqual(code,201)
        code,_=self.make_call(self.body(),nonce=nonce)
        self.assertEqual(code,403)

if __name__=="__main__":
    unittest.main()
