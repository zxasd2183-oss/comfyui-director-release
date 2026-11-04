import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from power_ops import (
    PowerError, build_plan, evaluate_action, get_provider_state, read_env_file,
    submit_power_request, get_queue_state,
)
from powerctl import operate

CFG = {
    "COMP_PUBLIC_KEY": "test-public", "COMP_PRIVATE_KEY": "test-private",
    "COMP_UHOST_ID": "uhost-test", "COMP_REGION": "cn-sh2",
    "COMP_ZONE": "cn-sh2-01",
}

class FakeClient:
    def __init__(self, state="Running", spot=False, fail=False):
        self.state = state
        self.spot = spot
        self.fail = fail
        self.actions = []

    def ucompshare(self):
        return self

    def invoke(self, name, params):
        self.actions.append((name, dict(params)))
        if self.fail:
            raise RuntimeError("secret-should-never-be-printed")
        if name == "DescribeCompShareInstance":
            return {"RetCode": 0, "UHostSet": [{
                "UHostId": "uhost-test", "Region": "cn-sh2",
                "Zone": "cn-sh2-01", "State": self.state,
                "GpuType": "5090", "ChargeType": "Postpay",
                "IsSpot": self.spot, "Password": "secret-do-not-output",
            }]}
        return {"RetCode": 0, "UHostId": "uhost-test"}

class PowerTests(unittest.TestCase):
    def test_state_is_redacted(self):
        state = get_provider_state(CFG, FakeClient("Running"))
        self.assertEqual(state["state"], "Running")
        self.assertNotIn("Password", str(state))
        self.assertNotIn("test-private", str(state))

    def test_start_requires_stopped(self):
        plan = build_plan("start", CFG, FakeClient("Stopped"))
        self.assertTrue(plan["allowed"])
        self.assertFalse(build_plan("start", CFG, FakeClient("Running"))["allowed"])

    def test_stop_requires_queue_verification(self):
        self.assertFalse(build_plan("stop", CFG, FakeClient("Running"),
                                    queue_check=lambda _: {"verified":False})["allowed"])
        self.assertFalse(build_plan("stop", CFG, FakeClient("Running"),
                                    queue_check=lambda _: {"verified":True, "empty":False,
                                                           "running":1, "pending":0})["allowed"])
        ok = build_plan("stop", CFG, FakeClient("Running"),
                        queue_check=lambda _: {"verified":True, "empty":True,
                                               "running":0, "pending":0})
        self.assertTrue(ok["allowed"])

    def test_spot_instance_blocked(self):
        blocked = build_plan("stop", CFG, FakeClient("Running", spot=True),
                             queue_check=lambda _: {"verified":True, "empty":True})
        self.assertFalse(blocked["allowed"])

    def test_submit_exact_provider_params(self):
        client=FakeClient()
        result=submit_power_request("stop", CFG, client)
        self.assertTrue(result["accepted"])
        self.assertEqual(client.actions[0], ("StopCompShareInstance", {
            "Region":"cn-sh2", "Zone":"cn-sh2-01", "UHostId":"uhost-test",
        }))
        self.assertEqual(result["instance_final_state"], "not_yet_verified")

    def test_network_failures_are_redacted(self):
        with self.assertRaises(PowerError) as caught:
            submit_power_request("stop", CFG, FakeClient(fail=True))
        self.assertNotIn("secret", str(caught.exception))

    def test_unverified_queue_blocks_stop(self):
        self.assertEqual(get_queue_state(CFG)["reason"], "queue_endpoint_not_configured")
        self.assertFalse(get_queue_state({**CFG,"DIRECTOR_GPU_QUEUE_URL":
                                        "http://example.com/queue"})["verified"])

    def test_h3_director_v3_queue_check(self):
        import io
        endpoint="https://example.trycloudflare.com/mcp/long-random-token"
        class Reply(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
            def geturl(self): return endpoint
        captured=[]
        def opener(req, timeout):
            self.assertEqual(req.get_method(),"POST")
            data=json.loads(req.data)
            self.assertEqual(data["params"]["name"],"get_queue_summary")
            captured.append(True)
            response={"jsonrpc":"2.0","id":1,"result":{
                "structuredContent":{"ok":True,"running":0,"pending":0,"read_only":True}
            }}
            return Reply(json.dumps(response).encode())
        status=get_queue_state({**CFG,"DIRECTOR_GPU_MCP_URL":endpoint},opener=opener)
        self.assertTrue(status["verified"])
        self.assertTrue(status["empty"])
        self.assertTrue(captured)

    def test_h3_director_v3_running_queue_blocks(self):
        import io
        endpoint="https://example.trycloudflare.com/mcp/test"
        class Reply(io.BytesIO):
            def geturl(self): return endpoint
        def opener(req, timeout):
            response={"jsonrpc":"2.0","id":1,"result":{
                "structuredContent":{"ok":True,"running":1,"pending":2}
            }}
            return Reply(json.dumps(response).encode())
        queue=get_queue_state({**CFG,"DIRECTOR_GPU_MCP_URL":endpoint},opener=opener)
        self.assertTrue(queue["verified"])
        self.assertFalse(queue["empty"])
        self.assertFalse(build_plan("stop",CFG,FakeClient("Running"),
                                   queue_check=lambda _:queue)["allowed"])

    def test_read_env_file_needs_root_only_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "env"
            path.write_text("\n".join(f"{k}={v}" for k,v in CFG.items()),encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(read_env_file(str(path))["COMP_REGION"],"cn-sh2")
            path.chmod(0o644)
            with self.assertRaises(PowerError):
                read_env_file(str(path))

    def test_local_cli_does_not_submit_on_plan(self):
        submitted=[]
        def plan(action, config):
            return {"allowed":True,"action":action}
        out=[]
        self.assertEqual(operate("start",apply=False,config=CFG,get_plan=plan,
                                 submit=lambda *_: submitted.append(1),output=out.append),0)
        self.assertEqual(submitted,[])

    def test_local_cli_blocks_missing_tty(self):
        submitted=[]
        with patch("powerctl.sys.stdin.isatty",return_value=False):
            rc=operate("stop",apply=True,config=CFG,
                       get_plan=lambda *args: {"allowed":True},
                       submit=lambda *_: submitted.append(1),
                       output=lambda _:None)
        self.assertEqual(rc,4)
        self.assertFalse(submitted)

    def test_local_cli_requires_correct_phrase_and_recheck(self):
        submissions=[]
        with patch("powerctl.sys.stdin.isatty",return_value=True):
            rc=operate("stop",apply=True,config=CFG,
                       get_plan=lambda *args: {"allowed":True},
                       submit=lambda *_: submissions.append(1),
                       input_fn=lambda _: "NOT THE RIGHT PHRASE",
                       output=lambda _:None)
        self.assertEqual(rc,5)
        self.assertFalse(submissions)
        plans=iter([{"allowed":True},{"allowed":False}])
        with patch("powerctl.sys.stdin.isatty",return_value=True):
            rc=operate("stop",apply=True,config=CFG,
                       get_plan=lambda *args: next(plans),
                       submit=lambda *_: submissions.append(1),
                       input_fn=lambda _: "STOP GPU - OUTPUTS VERIFIED SAVED",
                       output=lambda _:None)
        self.assertEqual(rc,6)
        self.assertFalse(submissions)

if __name__=="__main__":
    unittest.main()
