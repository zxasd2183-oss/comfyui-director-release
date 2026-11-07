"""Hub brain-link routing, signatures and argument least privilege."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT.parent/"studio"))
import hub_brain
import hub_rpc
import studio_brain

KEY="ab"*32


class Response:
    def __init__(self,url,body):
        self.url=url
        self.body=json.dumps(body).encode("utf-8")
        self.status=200
    def geturl(self):return self.url
    def read(self,limit):return self.body
    def __enter__(self):return self
    def __exit__(self,*args):return False


class Opener:
    def __init__(self,body=None):
        self.requests=[]
        self.body=body or {"ok":True,"counts":{"projects":0}}
    def open(self,req,timeout):
        self.requests.append(req)
        return Response(req.full_url,self.body)


class BrainRpcTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.key=self.root/"brain_link"
        self.key.write_text(KEY+"\n")
        self.key.chmod(0o600)
        self.env={"CREDENTIALS_DIRECTORY":self.temp.name}

    def test_ten_tools_are_distinct_from_power_and_gpu(self):
        self.assertEqual(len(hub_rpc.ALL_TOOLS),25)
        self.assertEqual(len(hub_rpc.BRAIN_TOOLS),10)
        self.assertFalse(hub_rpc.BRAIN_TOOLS & hub_rpc.POWER_TOOLS)
        self.assertFalse(hub_rpc.BRAIN_TOOLS & hub_rpc.GPU_TOOLS)
        for name in hub_rpc.BRAIN_TOOLS:
            self.assertEqual(hub_rpc.endpoint(name),hub_brain.STUDIO_URL)
        with self.assertRaises(hub_rpc.HubError):
            hub_rpc.check_args("run_shell",{})

    def test_signed_request_matches_studio_verifier(self):
        opener=Opener()
        args=hub_rpc.check_args("create_production_project",{
            "project_id":"WaitingOffice","title":"待回答事务所"})
        self.assertEqual(
            hub_brain.call_studio("create_production_project",args,
                environ=self.env,opener=opener,clock=lambda:1783500000,
                rand=lambda:"cd"*16)["ok"],True)
        req=opener.requests[0]
        self.assertEqual(req.full_url,"http://127.0.0.1:8900/api/v1/brain")
        self.assertEqual(req.get_method(),"POST")
        self.assertNotIn(KEY,str(req.data))
        self.assertNotIn(KEY,str(req.headers))
        headers={
            "Host":req.get_header("Host"),
            "X-Director-Brain-Time":req.get_header("X-director-brain-time"),
            "X-Director-Brain-Nonce":req.get_header("X-director-brain-nonce"),
            "X-Director-Brain-Signature":req.get_header("X-director-brain-signature")
        }
        auth=studio_brain.BrainAuthenticator(bytes.fromhex(KEY),clock=lambda:1783500000)
        self.assertTrue(auth.check(headers,"POST",studio_brain.BRAIN_PATH,
                                   req.data,"127.0.0.1"))

    def test_bad_args_never_cross_to_studio_or_gpu(self):
        valid={"project_id":"WaitingOffice","episode_id":"EP01",
               "title":"Episode","ordinal":1}
        for tool,args in [
            ("create_production_episode",{**valid,"cloud":"run"}),
            ("add_production_shot",{"project_id":"WaitingOffice",
                 "episode_id":"EP01","shot_id":"../../etc",
                 "ordinal":1,"duration_ms":2000}),
            ("get_production_dashboard",{"private":"secret"}),
            ("save_production_outline",{
                 "project_id":"WaitingOffice","episode_id":"EP01",
                 "body":"x"*12001,"expected_revision":0}),
            ("create_production_project",{"project_id":"DROP TABLE",
                                          "title":"Bad"}),
            ("create_production_episode",{**valid,"ordinal":True}),
        ]:
            with self.subTest(tool=tool,args=str(args)[:60]):
                with self.assertRaises(hub_rpc.HubError):
                    hub_rpc.check_args(tool,args)
        self.assertEqual(hub_rpc.check_args("get_production_dashboard",{}),{})

    def test_missing_or_symlink_credentials_refuse_without_transport(self):
        opener=Opener()
        self.key.unlink()
        self.assertEqual(hub_brain.call_studio("get_production_dashboard",{},
            environ=self.env,opener=opener)["reason"],"brain_link_not_configured")
        fake=self.root/"fake"
        fake.write_text(KEY)
        self.key.symlink_to(fake)
        self.assertEqual(hub_brain.call_studio("get_production_dashboard",{},
            environ=self.env,opener=opener)["reason"],"brain_link_not_configured")
        self.assertFalse(opener.requests)

    def test_late_response_and_invalid_nonce_block_without_secret(self):
        opener=Opener()
        data=hub_brain.call_studio("get_production_dashboard",{},environ=self.env,
            opener=opener,rand=lambda:"not-a-valid-nonce")
        self.assertEqual(data["reason"],"brain_nonce_invalid")
        self.assertFalse(opener.requests)

    def test_hub_rpc_dispatches_brain_tool_only_via_private_link(self):
        with patch.object(hub_rpc,"call_studio",return_value={
                "ok":True,"project_id":"WaitingOffice"}) as mocked:
            result=hub_rpc.call("create_production_project",{
                "project_id":"WaitingOffice","title":"New Project"})
        self.assertTrue(result["ok"])
        mocked.assert_called_once_with("create_production_project",{
            "project_id":"WaitingOffice","title":"New Project"})


if __name__=="__main__":unittest.main()
