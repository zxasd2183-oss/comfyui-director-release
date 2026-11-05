"""Owner-only Studio visual gallery: immutable bytes, scoped reads, audit selections."""
import base64
import http.client
import json
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import production_core as prod
import visual_library as media
import studio_server as server

PNG=bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082"
)
SUB="owner_identity_visual_tests_0123456789"
SID="q"*43
CSRF="owner_visual_csrf_token"


class MockOwner:
    def check(self,sid):
        return {"sub":SUB,"csrf":CSRF} if sid==SID else None


class VisualLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=str(Path(self.temp.name)/"production.sqlite")
        with closing(prod.open_db(self.db)) as db:
            prod.create_project(db,"WaitingOffice","待回答事务所")
            prod.create_episode(db,"WaitingOffice","EP01","第一集",1)
            prod.create_episode(db,"WaitingOffice","EP02","第二集",2)
            media.prepare_schema(db)

    def upload(self,subject="CHAR_GEM",kind="character",raw=PNG):
        return media.upload_visual(self.db,{
            "project_id":"WaitingOffice","episode_id":"EP01","kind":kind,
            "subject_id":subject,"filename":"旧角色图.png",
            "image_base64":base64.b64encode(raw).decode("ascii")
        },"owner_test")

    def test_versioned_gallery_preview_and_audit(self):
        first=self.upload()
        second=self.upload()
        self.assertEqual(first["version"],1)
        self.assertEqual(second["version"],2)
        self.assertNotEqual(first["visual_id"],second["visual_id"])
        self.assertEqual(
            media.read_visual(self.db,"WaitingOffice","EP01",first["visual_id"]),
            ("image/png",PNG))
        m=media.list_visuals(self.db,"WaitingOffice","EP01")
        self.assertEqual(len(m["visuals"]),2)
        self.assertFalse(any(v["selected"] for v in m["visuals"]))
        media.select_visual(self.db,{"project_id":"WaitingOffice",
            "episode_id":"EP01","visual_id":first["visual_id"]},"owner_test")
        m=media.list_visuals(self.db,"WaitingOffice","EP01")
        self.assertEqual(sum(v["selected"] for v in m["visuals"]),1)
        self.assertTrue(next(v for v in m["visuals"]
            if v["visual_id"]==first["visual_id"])["selected"])
        media.select_visual(self.db,{"project_id":"WaitingOffice",
            "episode_id":"EP01","visual_id":second["visual_id"]},"owner_test")
        m=media.list_visuals(self.db,"WaitingOffice","EP01")
        self.assertEqual(sum(v["selected"] for v in m["visuals"]),1)
        self.assertTrue(next(v for v in m["visuals"]
            if v["visual_id"]==second["visual_id"])["selected"])
        self.assertEqual(
            media.read_visual(self.db,"WaitingOffice","EP01",first["visual_id"])[1],PNG)
        with closing(prod.open_db(self.db,initialize=False)) as db:
            self.assertTrue(prod.verify_chain(db))
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM visual_selections").fetchone()[0],2)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM visual_media").fetchone()[0],2)

    def test_no_cross_episode_read_or_select(self):
        v=self.upload()
        with self.assertRaises(media.VisualError):
            media.read_visual(self.db,"WaitingOffice","EP02",v["visual_id"])
        with self.assertRaises(media.VisualError):
            media.select_visual(self.db,{"project_id":"WaitingOffice",
                "episode_id":"EP02","visual_id":v["visual_id"]},"owner_test")
        self.assertEqual(media.list_visuals(self.db,"WaitingOffice","EP02")["visuals"],[])

    def test_invalid_inputs_cannot_mutate(self):
        with self.assertRaises(media.VisualError):
            self.upload(raw=b"<script>alert(1)</script>")
        with self.assertRaises(media.VisualError):
            self.upload(raw=b"x"*(media.MAX_IMAGE_BYTES+1))
        with self.assertRaises(media.VisualError):
            media.upload_visual(self.db,{
                "project_id":"WaitingOffice","episode_id":"EP01","kind":"character",
                "subject_id":"CHAR_GEM","filename":"../../escape.png",
                "image_base64":base64.b64encode(PNG).decode("ascii")},"owner")
        with closing(prod.open_db(self.db,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],0)
            self.assertTrue(prod.verify_chain(db))


class VisualHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app=server.StudioServer(str(Path(self.temp.name)/"studio.sqlite"),
            poller=server.Poller(probe=lambda tool:{"ok":False,"reason":"offline"}),
            bind=("127.0.0.1",0))
        self.app.identity=MockOwner()
        with closing(prod.open_db(self.app.production_db_path)) as db:
            prod.create_project(db,"WaitingOffice","待回答事务所")
            prod.create_episode(db,"WaitingOffice","EP01","第一集",1)
        self.thread=threading.Thread(target=self.app.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.app.shutdown();self.app.server_close();self.thread.join(3)

    def call(self,method,path,data=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.app.server_port,timeout=8)
        h={"Host":"127.0.0.1:8900","X-Forwarded-Proto":"https",
           "X-Forwarded-Host":"jipite.borealos.cn",
           "X-Director-Studio-Auth-Mode":"microsoft",
           "Cookie":"__Secure-director_studio_sid="+SID,**(headers or {})}
        raw=json.dumps(data).encode("utf-8") if data is not None else None
        conn.request(method,path,raw,headers=h)
        res=conn.getresponse();payload=res.read()
        typ=res.getheader("Content-Type","")
        value=json.loads(payload) if "application/json" in typ and payload else payload
        code=res.status
        conn.close()
        return code,value

    def test_owner_upload_preview_and_reject_unauthorized(self):
        query="/api/v1/production/visuals?project=WaitingOffice&episode=EP01"
        status,_=self.call("GET",query,headers={"Cookie":""})
        self.assertEqual(status,401)
        status,_=self.call("GET",query)
        self.assertEqual(status,200)
        data={"csrf":CSRF,"project_id":"WaitingOffice","episode_id":"EP01",
              "kind":"character","subject_id":"CHAR_GEM","filename":"generated.png",
              "image_base64":base64.b64encode(PNG).decode("ascii")}
        url="/api/v1/production/visual/upload"
        headers={"Origin":"https://jipite.borealos.cn",
                 "Content-Type":"application/json"}
        status,_=self.call("POST",url,{**data,"csrf":"bad"},headers)
        self.assertEqual(status,403)
        status,out=self.call("POST",url,data,headers)
        self.assertEqual(status,201)
        self.assertFalse(out["gpu_action"])
        target="/api/v1/production/visual?project=WaitingOffice&episode=EP01&id="+out["visual_id"]
        status,png=self.call("GET",target)
        self.assertEqual(status,200)
        self.assertEqual(png,PNG)
        status,_=self.call("GET",target,headers={"Cookie":""})
        self.assertEqual(status,401)
        status,result=self.call("POST","/api/v1/production/visual/select",
            {"csrf":CSRF,"project_id":"WaitingOffice","episode_id":"EP01",
             "visual_id":out["visual_id"]},headers)
        self.assertEqual(status,200)
        self.assertTrue(result["selected"])
        status,gallery=self.call("GET",query)
        self.assertTrue(gallery["visuals"][0]["selected"])


if __name__=="__main__":
    unittest.main()
