"""Real loopback HTTP boundary for owner-issued scoped GPU return credentials."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_server as server
from studio_identity import COOKIE_SID
from production_core import open_db, create_project, create_episode
from gpu_return import issue, authenticate, ReturnError

SESSION="z"*43
CSRF="test-owner-csrf"
SUB="owner_test_account_123456"


class Identity:
    def check(self,sid):
        return {"sub":SUB,"csrf":CSRF} if sid==SESSION else None


class ReturnTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app=server.StudioServer(self.temp.name+"/studio.sqlite",
            poller=server.Poller(probe=lambda _:{"ok":False}),
            bind=("127.0.0.1",0))
        self.app.identity=Identity()
        with open_db(self.app.production_db_path) as db:
            create_project(db,"WaitingOffice","The Office")
            create_episode(db,"WaitingOffice","EP01","First Episode",1)
            create_episode(db,"WaitingOffice","EP02","Second Episode",2)
        self.thread=threading.Thread(target=self.app.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.app.shutdown()
        self.app.server_close()
        self.thread.join(3)

    def post(self,path,body,token=None,cookie=None,origin=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.app.server_port,timeout=6)
        headers={"Host":"127.0.0.1:8900","Content-Type":"application/json",
            "X-Forwarded-Proto":"https",
            "X-Forwarded-Host":"jipite.borealos.cn",
            "X-Director-Studio-Auth-Mode":"microsoft"}
        if cookie:headers["Cookie"]=COOKIE_SID+"="+cookie
        if token:headers["Authorization"]="Bearer "+token
        if origin:headers["Origin"]=origin
        conn.request("POST",path,json.dumps(body).encode(),headers)
        response=conn.getresponse()
        status=response.status
        data=json.loads(response.read())
        conn.close()
        return status,data

    def owner_issue(self,episode="EP01"):
        return self.post("/api/v1/gpu-return-token/issue",{
            "csrf":CSRF,"project_id":"WaitingOffice","episode_id":episode},
            cookie=SESSION,origin="https://jipite.borealos.cn")

    def test_only_microsoft_owner_can_issue_and_secret_not_stored(self):
        status,_=self.post("/api/v1/gpu-return-token/issue",{
            "csrf":CSRF,"project_id":"WaitingOffice","episode_id":"EP01"})
        self.assertEqual(status,401)
        status,created=self.owner_issue()
        self.assertEqual(status,201,created)
        self.assertEqual(created["permissions"],["video_import_in_review_only"])
        secret=created["token"]
        db=Path(self.app.production_db_path).read_bytes()
        self.assertNotIn(secret.encode(),db)
        credential=authenticate(self.app.production_db_path,"Bearer "+secret)
        self.assertEqual(credential["episode_id"],"EP01")

    def test_new_token_revokes_previous(self):
        one=self.owner_issue()[1]["token"]
        two=self.owner_issue()[1]["token"]
        with self.assertRaisesRegex(ReturnError,"expired_or_invalid"):
            authenticate(self.app.production_db_path,"Bearer "+one)
        self.assertEqual(authenticate(self.app.production_db_path,"Bearer "+two)
                         ["project_id"],"WaitingOffice")

    def test_bearer_upload_still_requires_correct_scope_and_never_approves(self):
        token=self.owner_issue()[1]["token"]
        payload={"project_id":"WaitingOffice","episode_id":"EP01",
                 "shot_id":"01","plan_revision":1,"package_sha256":"a"*64,
                 "file_sha256":"b"*64,"size_bytes":1024,"prompt_id":"p123"}
        status,doc=self.post("/api/v1/gpu-return/start",payload)
        self.assertEqual(status,401)
        status,doc=self.post("/api/v1/gpu-return/start",
                             {**payload,"episode_id":"EP02"},token=token)
        self.assertEqual(status,403)
        with patch.object(server,"begin_video_upload",return_value={
                "ok":True,"upload_id":"UP_"+"a"*32,"status":"in_review"}) as submit:
            status,doc=self.post("/api/v1/gpu-return/start",payload,token=token)
            self.assertEqual(status,200,doc)
            self.assertEqual(doc["status"],"in_review")
            self.assertTrue(submit.call_args.args[2].startswith("gpureturn_"))
        status,doc=self.post("/api/v1/gpu-return/review",payload,token=token)
        self.assertEqual(status,404)

    def test_cookie_does_not_replace_gpu_token(self):
        token=self.owner_issue()[1]["token"]
        status,_=self.post("/api/v1/gpu-return/start",{},cookie=SESSION,
                           origin="https://jipite.borealos.cn")
        self.assertEqual(status,401)
        status,_=self.post("/api/v1/gpu-return-token/issue",{
            "csrf":"wrong","project_id":"WaitingOffice","episode_id":"EP01"},
            cookie=SESSION,origin="https://jipite.borealos.cn")
        self.assertEqual(status,403)
        status,_=self.post("/api/v1/gpu-return/start",{},token=token)
        self.assertEqual(status,403) # empty start cannot specify token's scope

    def test_invalid_token_is_not_accepted(self):
        for header in ("Bearer invalid","Bearer "+"x"*48, "Basic user:pass",""):
            with self.subTest(header=header[:12]):
                with self.assertRaises(ReturnError):
                    authenticate(self.app.production_db_path,header)


if __name__=="__main__":
    unittest.main()
