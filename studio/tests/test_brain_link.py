"""Director Studio Brain link integration: authenticated local MCP planning only."""
from __future__ import annotations
import hashlib
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"vps-control"))
from studio_brain import BrainAuthenticator,signature,BRAIN_PATH
from studio_server import StudioServer,Poller
from production_core import open_db,verify_chain


KEY=bytes.fromhex("ab"*32)
STAMP="1783500000"
NONCE="cd"*16


class BrainLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.svc=StudioServer(self.tmp.name+"/studio.sqlite",bind=("127.0.0.1",0),
                              poller=Poller(probe=lambda _:{"ok":False,"reason":"test"}))
        self.now=[1783500000]
        self.svc.brain_auth=BrainAuthenticator(KEY,clock=lambda:self.now[0])
        self.thread=threading.Thread(target=self.svc.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.svc.shutdown()
        self.svc.server_close()
        self.thread.join(3)

    def ask(self,tool,args,*,nonce=NONCE,body_override=None,headers=None):
        raw=body_override if body_override is not None else json.dumps({
            "tool":tool,"arguments":args},ensure_ascii=False).encode()
        mac=signature(KEY,"POST",BRAIN_PATH,STAMP,nonce,raw)
        h={"Host":"127.0.0.1:8900","Content-Type":"application/json",
           "X-Director-Brain-Time":STAMP,
           "X-Director-Brain-Nonce":nonce,
           "X-Director-Brain-Signature":mac,
           **(headers or {})}
        conn=http.client.HTTPConnection("127.0.0.1",self.svc.server_port,timeout=5)
        conn.request("POST",BRAIN_PATH,raw,headers=h)
        response=conn.getresponse();body=response.read()
        status=response.status;conn.close()
        return status,json.loads(body)

    def test_valid_signed_project_episode_outline_and_shot_roundtrip(self):
        status,result=self.ask("get_production_dashboard",{},nonce="01"*16)
        self.assertEqual(status,200)
        self.assertEqual(result["counts"]["projects"],0)
        status,result=self.ask("create_production_project",{
            "project_id":"WaitingOffice","title":"待回答事务所"},nonce="02"*16)
        self.assertEqual(status,200)
        self.assertFalse(result["gpu_action"])
        status,result=self.ask("create_production_episode",{
            "project_id":"WaitingOffice","episode_id":"EP01",
            "title":"第一集","ordinal":1},nonce="03"*16)
        self.assertEqual(status,200)
        text="第一幕：角色进入办公室。第二幕：悬念出现。导演审核前为草稿。"
        status,result=self.ask("save_production_outline",{
            "project_id":"WaitingOffice","episode_id":"EP01",
            "body":text,"expected_revision":0},nonce="04"*16)
        self.assertEqual(status,200)
        self.assertEqual(result["revision"],1)
        self.assertEqual(result["status"],"draft")
        status,result=self.ask("add_production_shot",{
            "project_id":"WaitingOffice","episode_id":"EP01","shot_id":"01",
            "ordinal":1,"duration_ms":4500},nonce="05"*16)
        self.assertEqual(status,200)
        status,result=self.ask("get_production_episode",{
            "project_id":"WaitingOffice","episode_id":"EP01"},nonce="06"*16)
        self.assertEqual(status,200)
        self.assertEqual(result["shot_count"],1)
        self.assertEqual(result["outline"]["body"],text)
        self.assertEqual(result["outline"]["revision"],1)
        with closing(open_db(self.svc.production_db_path,initialize=False)) as db:
            self.assertTrue(verify_chain(db))
            rows=db.execute("SELECT action,actor,detail FROM audit_chain ORDER BY id").fetchall()
            self.assertEqual(len(rows),4)
            self.assertTrue(all(row["actor"]=="studio_brain" for row in rows))
            self.assertNotIn(text,"".join(row["detail"] for row in rows))

    def test_unknown_tool_cannot_affect_gpu_or_approve_exception(self):
        for name in ("request_gpu_start","approve_exception","execute_shell"):
            status,result=self.ask(name,{},nonce=hashlib.md5(name.encode()).hexdigest())
            self.assertEqual(status,403)
            self.assertEqual(result["reason"],"brain_tool_not_allowed")

    def test_invalid_or_replayed_hmac_never_writes(self):
        args={"project_id":"WaitingOffice","title":"Private"}
        bad={
            "X-Director-Brain-Signature":"0"*64,
        }
        self.assertEqual(self.ask("create_production_project",args,
                                   nonce="11"*16,headers=bad)[0],403)
        for extra in (
            {"X-Forwarded-Host":"jipite.borealos.cn"},
            {"X-Forwarded-Proto":"https"},
            {"X-Director-Studio-Auth-Mode":"microsoft"},
            {"Origin":"https://jipite.borealos.cn"},
            {"Cookie":"studio_session=secret"},
        ):
            status,result=self.ask("create_production_project",args,
                                    nonce="12"*16,headers=extra)
            self.assertEqual(status,403)
        status,result=self.ask("create_production_project",args,nonce="13"*16)
        self.assertEqual(status,200)
        self.assertEqual(self.ask("create_production_project",args,nonce="13"*16)[0],403)
        with closing(open_db(self.svc.production_db_path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM projects").fetchone()[0],1)

    def test_stale_signed_request_fails_and_does_not_consume_nonce(self):
        args={"project_id":"WaitingOffice","title":"Private"}
        self.now[0]+=120
        status,result=self.ask("create_production_project",args)
        self.assertEqual(status,403)
        self.now[0]-=120
        self.assertEqual(self.ask("create_production_project",args)[0],200)

    def test_outline_optimistic_version_no_mutation_on_conflict(self):
        self.ask("create_production_project",{
            "project_id":"WaitingOffice","title":"Series"},nonce="21"*16)
        self.ask("create_production_episode",{
            "project_id":"WaitingOffice","episode_id":"EP01",
            "title":"Episode","ordinal":1},nonce="22"*16)
        one={"project_id":"WaitingOffice","episode_id":"EP01",
             "body":"初稿","expected_revision":0}
        self.assertEqual(self.ask("save_production_outline",one,nonce="23"*16)[0],200)
        bad={"project_id":"WaitingOffice","episode_id":"EP01",
             "body":"should never replace","expected_revision":0}
        status,result=self.ask("save_production_outline",bad,nonce="24"*16)
        self.assertEqual(status,409)
        self.assertEqual(result["reason"],"stale_outline_revision")
        status,result=self.ask("get_production_episode",{
            "project_id":"WaitingOffice","episode_id":"EP01"},nonce="25"*16)
        self.assertEqual(result["outline"]["body"],"初稿")
        self.assertEqual(result["outline"]["revision"],1)
        with closing(open_db(self.svc.production_db_path,initialize=False)) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM episode_outline_history").fetchone()[0],1)
            self.assertTrue(verify_chain(db))

    def test_missing_credential_fails_closed_even_with_other_valid_fields(self):
        self.svc.brain_auth=BrainAuthenticator(None)
        status,data=self.ask("get_production_dashboard",{})
        self.assertEqual(status,503)
        self.assertEqual(data["reason"],"brain_link_not_configured")

    def test_nonbrain_public_browser_cannot_read_private_outline(self):
        self.ask("create_production_project",{
            "project_id":"WaitingOffice","title":"Series"},nonce="31"*16)
        self.ask("create_production_episode",{
            "project_id":"WaitingOffice","episode_id":"EP01",
            "title":"Episode","ordinal":1},nonce="32"*16)
        self.ask("save_production_outline",{
            "project_id":"WaitingOffice","episode_id":"EP01",
            "body":"INTERNAL_OUTLINE_NOT_PUBLIC","expected_revision":0},nonce="33"*16)
        conn=http.client.HTTPConnection("127.0.0.1",self.svc.server_port,timeout=5)
        conn.request("GET","/api/v1/production",headers={
            "Host":"127.0.0.1:8900",
            "X-Director-Studio-Auth-Mode":"microsoft",
            "X-Forwarded-Proto":"https",
            "X-Forwarded-Host":"jipite.borealos.cn",
        })
        response=conn.getresponse()
        self.assertEqual(response.status,503) # Missing OIDC credentials means fail closed.
        self.assertNotIn(b"INTERNAL_OUTLINE",response.read())
        conn.close()


if __name__=="__main__":
    unittest.main()
