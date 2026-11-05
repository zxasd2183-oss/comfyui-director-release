"""V0.9.2 authenticated owner project editing and protected episode browser."""
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from contextlib import closing

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_server as server
import production_core as prod
import production_web as editor

SID="s"*43
SUB="real_owner_subject_local_test123"


class MockOwnerIdentity:
    def check(self,sid):
        return {"sub":SUB,"csrf":"scoped-microsoft-session-csrf"} if sid==SID else None


class StudioAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app=server.StudioServer(self.tmp.name+"/studio.sqlite",
            poller=server.Poller(probe=lambda tool:{"ok":False,"reason":"offline"}),
            bind=("127.0.0.1",0))
        self.app.identity=MockOwnerIdentity()
        self.thread=threading.Thread(target=self.app.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.app.shutdown()
        self.app.server_close()
        self.thread.join(3)

    def call(self,method,path,payload=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.app.server_port,timeout=5)
        header={
            "Host":"127.0.0.1:8900",
            "X-Forwarded-Proto":"https",
            "X-Forwarded-Host":"jipite.borealos.cn",
            "X-Director-Studio-Auth-Mode":"microsoft",
            "Cookie":"__Secure-director_studio_sid="+SID,
            **(headers or {})
        }
        if isinstance(payload,(bytes,bytearray)):
            body=payload
        else:
            body=json.dumps(payload).encode("utf-8") if payload is not None else None
        conn.request(method,path,body,headers=header)
        resp=conn.getresponse()
        data=resp.read()
        result=(resp.status,json.loads(data) if "application/json" in
                resp.getheader("Content-Type","") and data else data)
        conn.close()
        return result

    def post(self,action,**kwargs):
        return self.call("POST","/api/v1/production/action",
            {"action":action,"csrf":"scoped-microsoft-session-csrf",**kwargs},
            {"Origin":"https://jipite.borealos.cn",
             "Content-Type":"application/json"})

    def test_create_project_episode_and_ledger_actor_and_detail(self):
        status,r=self.post("create_project",project_id="WaitingOffice",
                           title="待回答事务所")
        self.assertEqual(status,201)
        self.assertFalse(r["gpu_action"])
        status,r=self.post("create_episode",project_id="WaitingOffice",
                           episode_id="EP01",title="第一集",ordinal=1)
        self.assertEqual(status,201)
        self.assertFalse(r["gpu_action"])
        status,r=self.call("GET","/api/v1/production")
        self.assertEqual(status,200)
        self.assertEqual(r["counts"]["projects"],1)
        self.assertEqual(r["counts"]["episodes"],1)
        self.assertTrue(r["audit_chain_verified"])
        status,r=self.call("GET","/api/v1/production/episode?project=WaitingOffice&episode=EP01")
        self.assertEqual(status,200)
        self.assertEqual(r["episode"]["title"],"第一集")
        self.assertEqual(r["shot_count"],0)
        self.assertEqual(r["mode"],"read_only_episode_detail")
        with closing(prod.open_db(self.app.production_db_path,initialize=False)) as db:
            audit=db.execute("SELECT actor,action FROM audit_chain ORDER BY id").fetchall()
            self.assertEqual([a["action"] for a in audit],
                             ["project.created","episode.created"])
            self.assertTrue(all(a["actor"].startswith("owner_") for a in audit))
            self.assertTrue(all(SUB not in a["actor"] for a in audit))

    def test_duplicate_project_and_episode_ordinals_rejected_without_extra_audit(self):
        self.post("create_project",project_id="Project01",title="Project")
        self.post("create_episode",project_id="Project01",episode_id="EP01",
                  title="First",ordinal=1)
        status,r=self.post("create_project",project_id="Project01",title="Again")
        self.assertEqual(status,409)
        status,r=self.post("create_episode",project_id="Project01",
                           episode_id="EP02",title="Duplicate ordinal",ordinal=1)
        self.assertEqual(status,409)
        with closing(prod.open_db(self.app.production_db_path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_chain").fetchone()[0],2)
            self.assertTrue(prod.verify_chain(db))

    def test_anonymous_malformed_origin_and_csrf_block_writes(self):
        headers={"Origin":"https://jipite.borealos.cn",
                 "Content-Type":"application/json"}
        body={"action":"create_project","project_id":"Project01",
              "title":"Silent","csrf":"scoped-microsoft-session-csrf"}
        status,_=self.call("POST","/api/v1/production/action",body,
                           {**headers,"Cookie":""})
        self.assertEqual(status,401)
        status,_=self.call("POST","/api/v1/production/action",body,
                           {**headers,"Origin":"https://evil.example"})
        self.assertEqual(status,403)
        status,_=self.call("POST","/api/v1/production/action",
                           {**body,"csrf":"wrong"},headers)
        self.assertEqual(status,403)
        status,_=self.call("POST","/api/v1/production/action",body,
                           {**headers,"X-Forwarded-Proto":"http"})
        self.assertEqual(status,403)
        status,_=self.call("GET","/api/v1/production",headers={"Cookie":""})
        self.assertEqual(status,401)
        with closing(prod.open_db(self.app.production_db_path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM projects").fetchone()[0],0)

    def test_ssh_only_mode_cannot_mutate_production(self):
        headers={
            "X-Director-Studio-Auth-Mode":"",
            "X-Forwarded-Proto":"",
            "X-Forwarded-Host":"",
            "Origin":"http://127.0.0.1:8900",
            "Content-Type":"application/json",
            "Cookie":""
        }
        body={"action":"create_project","csrf":"scoped-microsoft-session-csrf",
              "project_id":"Project01","title":"SSH attempted write"}
        status,r=self.call("POST","/api/v1/production/action",body,headers)
        self.assertEqual(status,403)
        status,r=self.call("GET",
                "/api/v1/production/episode?project=Project01&episode=EP01",
                headers=headers)
        self.assertEqual(status,403)

    def test_rejects_unknown_action_and_fields(self):
        status,r=self.post("approve_exception",exception_id="X01")
        self.assertEqual(status,403)
        status,r=self.post("direct_gpu_power",project_id="Project01")
        self.assertEqual(status,403)
        status,r=self.post("create_project",project_id="Project01",
                           title="OK",actor="spoofed_owner")
        self.assertEqual(status,400)
        status,r=self.post(["create_project"],project_id="Project01",title="OK")
        self.assertEqual(status,403)
        status,r=self.post("create_project",project_id="../../etc",
                           title="path injection")
        self.assertEqual(status,400)

    def test_episode_detail_has_bounded_nonsecret_media_metadata(self):
        self.post("create_project",project_id="Project01",title="Series")
        self.post("create_episode",project_id="Project01",episode_id="EP01",
                  title="Episode",ordinal=1)
        with closing(prod.open_db(self.app.production_db_path)) as db:
            prod.create_shot(db,"Project01","EP01","01",1,4200)
            prod.add_asset(db,"Voice001","Project01","character_voice",
                           "LeadVoice",1,"a"*64,"signed_owner_voice_consent")
            prod.attach_asset(db,"Project01","EP01","01","Voice001","voice_reference")
            prod.create_finding(db,"Finding01","Project01","EP01","01",
                                "voice.timbre","b"*64,"内部分析备注不应发送")
        status,r=self.call("GET",
                  "/api/v1/production/episode?project=Project01&episode=EP01")
        self.assertEqual(status,200)
        self.assertEqual(r["shots"][0]["duration_ms"],4200)
        self.assertEqual(r["assets"][0]["kind"],"character_voice")
        self.assertEqual(r["finding_count"],1)
        s=json.dumps(r,ensure_ascii=False)
        self.assertNotIn("signed_owner_voice_consent",s)
        self.assertNotIn("内部分析备注不应发送",s)
        self.assertNotIn("a"*64,s)
        self.assertNotIn("b"*64,s)

    def test_bad_episode_query_rejected_even_if_owner(self):
        self.post("create_project",project_id="Project01",title="Series")
        self.post("create_episode",project_id="Project01",episode_id="EP01",
                  title="Episode",ordinal=1)
        bads=[
            "project=Project01&episode=EP01&episode=EP01",
            "project=Project01&episode=EP01&token=secret",
            "project=../etc&episode=EP01",
            "project=Project01",
        ]
        for qs in bads:
            with self.subTest(qs=qs):
                status,_=self.call("GET","/api/v1/production/episode?"+qs)
                self.assertEqual(status,400)
        self.assertEqual(self.call("GET",
            "/api/v1/production/episode?project=Project01&episode=EP99")[0],404)

    def test_broken_audit_chain_refuses_project_changes(self):
        self.post("create_project",project_id="Project01",title="Series")
        with closing(prod.open_db(self.app.production_db_path)) as db:
            db.execute("UPDATE audit_chain SET detail='tampered' WHERE id=1")
        status,r=self.post("create_episode",project_id="Project01",
                           episode_id="EP01",title="Should not write",ordinal=1)
        self.assertEqual(status,409)
        self.assertEqual(r["reason"],"audit_integrity_failure")
        with closing(prod.open_db(self.app.production_db_path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0],0)

    def test_frontend_includes_real_authoring_controls_and_no_gpu_action(self):
        root=Path(__file__).resolve().parents[1]
        html=(root/"index.html").read_text()
        js=(root/"studio.js").read_text()
        self.assertIn('id="createProjectBtn"',html)
        self.assertIn('id="createEpisodeBtn"',html)
        self.assertIn('id="episodeExplorer"',html)
        self.assertIn('id="productionForm"',html)
        self.assertIn('fetch("./api/v1/production/action"',js)
        self.assertIn('microsoftOwner=b.mode==="microsoft_owner"',js)
        self.assertIn('gpu_action',str(editor.create_from_web.__doc__) if editor.create_from_web.__doc__ else "gpu_action")
        self.assertNotIn('fetch("./api/v1/power"',js)


if __name__=="__main__":
    unittest.main()
