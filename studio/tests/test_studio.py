import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import studio_core as core
import studio_backend as backend
import studio_server as server
import manage


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dbfile = self.root / "operator.sqlite"
        self.planfile = self.root / "plan.json"
        self.planfile.write_text(json.dumps({"schema": 1, "jobs": [
            {"shot_id": "01", "seconds": 5, "graph": {"6": {"class_type": "Text",
                "inputs": {"prompt": "secret prompt 01"}}}},
            {"shot_id": "02", "seconds": 3, "graph": {"6": {"class_type": "Text",
                "inputs": {"prompt": "secret prompt 02"}}}}
        ]}), encoding="utf-8")
        self.db = core.connect(self.dbfile)
        self.addCleanup(self.db.close)

    def import_shots(self):
        return core.import_plan(self.db, self.planfile)

    def test_only_redacted_shot_fields_stored(self):
        result = self.import_shots()
        self.assertEqual(result["shot_count"], 2)
        s = core.snapshot(self.db)
        self.assertEqual(s["shots"][0]["id"], "01")
        self.assertTrue(s["dispatch_paused"])
        self.assertEqual(s["mode"], "operator_ledger_only")
        self.assertNotIn("secret prompt", json.dumps(s))
        self.assertNotIn("secret prompt", self.dbfile.read_bytes().decode("utf-8", "ignore"))
        self.assertTrue(self.import_shots()["unchanged"])

    def test_pause_resume_and_hold_affect_eligible_list(self):
        self.import_shots()
        self.assertEqual(core.dispatch_eligible(self.db), [])
        core.decide(self.db,"resume_dispatch")
        self.assertEqual(core.dispatch_eligible(self.db), ["01","02"])
        core.decide(self.db,"hold_shot",shot_id="01",revision=0)
        self.assertEqual(core.dispatch_eligible(self.db), ["02"])
        core.decide(self.db,"pause_dispatch")
        self.assertEqual(core.dispatch_eligible(self.db), [])
        s = core.snapshot(self.db)
        self.assertEqual(s["shots"][0]["revision"], 1)
        self.assertFalse(s["dispatch_paused"] is False)
        self.assertEqual(s["events"][0]["action"], "pause_dispatch")

    def test_approval_refused_without_verified_review_artifact(self):
        self.import_shots()
        with self.assertRaisesRegex(core.StudioError,"review_artifact_not_verified"):
            core.decide(self.db,"approve_shot",shot_id="01",revision=0)
        self.assertEqual(core.snapshot(self.db)["shots"][0]["review"],"pending")

    def test_stale_revision_and_rework_notes(self):
        self.import_shots()
        with self.assertRaisesRegex(core.StudioError,"reason_required"):
            core.decide(self.db,"request_rework",shot_id="01",revision=0)
        out=core.decide(self.db,"request_rework",shot_id="01",revision=0,
                        reason="人物服装与设定不一致")
        self.assertFalse(out["executed_on_gpu"])
        with self.assertRaisesRegex(core.StudioError,"stale_shot_revision"):
            core.decide(self.db,"hold_shot",shot_id="01",revision=0)
        s=core.snapshot(self.db)
        self.assertTrue(s["shots"][0]["held"])
        self.assertEqual(s["shots"][0]["review"],"rework")
        self.assertIn("人物服装",s["events"][0]["detail"])

    def test_plan_replacement_rejected(self):
        self.import_shots()
        changed=json.loads(self.planfile.read_text())
        changed["jobs"][0]["shot_id"]="03"
        self.planfile.write_text(json.dumps(changed))
        with self.assertRaisesRegex(core.StudioError,"new_database"):
            self.import_shots()
        self.assertEqual(len(core.snapshot(self.db)["shots"]),2)

    def test_runner_status_import_only_changes_metadata(self):
        self.import_shots()
        file=self.root/"runner.sqlite"
        with closing(sqlite3.connect(file)) as runner:
            runner.execute("CREATE TABLE runs(shot_id TEXT,state TEXT,prompt_id TEXT)")
            runner.execute("INSERT INTO runs VALUES ('01','queued','do-not-publish')")
            runner.execute("INSERT INTO runs VALUES ('02','done','secret-prompt')")
            runner.commit()
        v=manage.sync_runner(self.db,file)
        self.assertEqual(v,{"ok":True,"changed":2,"real_time_sync":False})
        shots=core.snapshot(self.db)["shots"]
        self.assertEqual([x["stage"] for x in shots],["queued","rendered"])
        self.assertNotIn("do-not-publish",json.dumps(core.snapshot(self.db)))
        self.assertEqual(manage.sync_runner(self.db,file)["changed"],0)

    def test_runner_unknown_shot_rolls_back(self):
        self.import_shots()
        file=self.root/"runner.sqlite"
        with closing(sqlite3.connect(file)) as runner:
            runner.execute("CREATE TABLE runs(shot_id TEXT,state TEXT)")
            runner.execute("INSERT INTO runs VALUES ('01','queued')")
            runner.execute("INSERT INTO runs VALUES ('99','queued')")
            runner.commit()
        with self.assertRaisesRegex(core.StudioError,"not_in_plan"):
            manage.sync_runner(self.db,file)
        self.assertEqual(core.snapshot(self.db)["shots"][0]["stage"],"planned")

    def test_duplicate_and_invalid_shot_are_refused(self):
        obj=json.loads(self.planfile.read_text())
        obj["jobs"][1]["shot_id"]="01"
        self.planfile.write_text(json.dumps(obj))
        with self.assertRaisesRegex(core.StudioError,"invalid_shot"):
            self.import_shots()
        self.assertEqual(len(core.snapshot(self.db)["shots"]),0)

    def test_no_direct_gpu_mutation_tools(self):
        self.assertFalse({"interrupt_gpu","stop_gpu","cancel_gpu_job"} & core.COMMANDS)
        self.import_shots()
        with self.assertRaisesRegex(core.StudioError,"invalid_command"):
            core.decide(self.db,"request_gpu_start")
        s=core.snapshot(self.db)
        self.assertFalse(s["capabilities"]["direct_gpu_power"])
        self.assertFalse(s["capabilities"]["interrupt_running_comfyui"])


class FakeResponse:
    def __init__(self,url,obj):
        self.url,self.obj=url,json.dumps(obj).encode()
    def geturl(self):return self.url
    def read(self,limit):return self.obj
    def __enter__(self):return self
    def __exit__(self,*a):return False

class FakeOpener:
    def __init__(self,response):
        self.response=response
        self.requests=[]
    def open(self,req,timeout):
        self.requests.append(req)
        return FakeResponse(req.full_url,self.response)


class BackendTests(unittest.TestCase):
    def test_strict_allowlist_and_no_power_actions(self):
        self.assertEqual(backend.query("request_gpu_stop")["reason"],
                         "read_only_tool_not_allowed")
        self.assertEqual(backend.query("get_studio_status")["reason"],
                         "read_only_tool_not_allowed")
        self.assertEqual(backend.query("get_gpu_power_status",port=19201)["reason"],
                         "hub_port_not_allowed")

    def test_hub_status_redaction_and_local_routing(self):
        mock=FakeOpener({"jsonrpc":"2.0","id":1,"result":{"structuredContent":{
            "ok":True,"state":"Stopped","gpu_type":"5090","mode":"read_only",
            "COMP_PRIVATE_KEY":"must-never-appear","instance_id":"private"}}})
        status=backend.query("get_gpu_power_status",port=8898,opener=mock)
        self.assertEqual(status,{"ok":True,"state":"Stopped",
                                 "gpu_type":"5090","mode":"read_only"})
        req=mock.requests[0]
        self.assertEqual(req.full_url,"http://127.0.0.1:8898/mcp")
        self.assertEqual(json.loads(req.data)["params"]["name"],"get_gpu_power_status")
        self.assertNotIn("must-never-appear",json.dumps(status))

    def test_hub_queue_status_is_strictly_numeric(self):
        mock=FakeOpener({"jsonrpc":"2.0","id":1,"result":{
            "structuredContent":{"ok":True,"running":1,"pending":2}}})
        self.assertEqual(backend.query("get_queue_summary",opener=mock),
                         {"ok":True,"running":1,"pending":2})
        invalid=FakeOpener({"jsonrpc":"2.0","id":1,"result":{
            "structuredContent":{"ok":True,"running":True,"pending":0}}})
        self.assertEqual(backend.query("get_queue_summary",opener=invalid)["ok"],False)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service=server.StudioServer(self.tmp.name+"/db.sqlite",bind=("127.0.0.1",0),
            poller=server.Poller(probe=lambda name:{"ok":True,"state":"Stopped"}))
        self.thread=threading.Thread(target=self.service.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_service)
    def stop_service(self):
        self.service.shutdown()
        self.service.server_close()
        self.thread.join(timeout=3)
    def call(self,method,path,payload=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.service.server_port,timeout=4)
        h={"Host":"127.0.0.1:8900",**(headers or {})}
        body=json.dumps(payload).encode() if payload is not None else None
        conn.request(method,path,body=body,headers=h)
        resp=conn.getresponse()
        content=resp.read()
        data=json.loads(content) if resp.getheader("Content-Type","").startswith("application/json") else content
        result=(resp.status,dict(resp.getheaders()),data)
        conn.close()
        return result
    def test_snapshot_bootstrap_local_only(self):
        status,headers,value=self.call("GET","/api/v1/bootstrap")
        self.assertEqual(status,200)
        self.assertGreater(len(value["csrf"]),30)
        self.assertEqual(headers["Content-Security-Policy"],server.CSP)
        status,_,value=self.call("GET","/api/v1/snapshot")
        self.assertEqual(status,200)
        self.assertEqual(value["mode"],"operator_ledger_only")
        self.assertIn("live",value)
        status,_,_=self.call("GET","/",headers={"Host":"attacker.invalid"})
        self.assertEqual(status,403)
    def test_post_requires_origin_csrf_and_json(self):
        status,_,boot=self.call("GET","/api/v1/bootstrap")
        csrf=boot["csrf"]
        request={"csrf":csrf,"action":"pause_dispatch"}
        self.assertEqual(self.call("POST","/api/v1/action",request,
            {"Content-Type":"application/json"})[0],403)
        self.assertEqual(self.call("POST","/api/v1/action",{**request,"csrf":"wrong"},
            {"Origin":"http://127.0.0.1:8900","Content-Type":"application/json"})[0],403)
        status,_,result=self.call("POST","/api/v1/action",request,{
            "Origin":"http://127.0.0.1:8900","Content-Type":"application/json"})
        self.assertEqual(status,200)
        self.assertFalse(result["executed_on_gpu"])
        self.assertEqual(result["effect"],"operator_ledger_only")
    def test_static_frontend_has_no_remote_scripts(self):
        for path in ("/","/studio.css","/studio.js"):
            code,_,content=self.call("GET",path)
            self.assertEqual(code,200)
            self.assertNotIn(b"https://",content)
        self.assertIn(b"EventSource",self.call("GET","/studio.js")[2])


if __name__=="__main__":
    unittest.main()
