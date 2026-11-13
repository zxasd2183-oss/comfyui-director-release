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
    def test_ucloud_sdk_logging_disabled(self):
        import logging
        logger = logging.getLogger("ucloud")
        logger.disabled = False
        get_provider_state(CFG, FakeClient("Running"))
        self.assertTrue(logger.disabled)

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
                                    queue_check=lambda _: {"verified":True, "source":"ue_worker",
                                                           "empty":False, "running":1, "pending":0})["allowed"])
        ok = build_plan("stop", CFG, FakeClient("Running"),
                        queue_check=lambda _: {"verified":True, "source":"ue_worker",
                                               "empty":True, "running":0, "pending":0})
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


    def test_legacy_comfyui_looking_report_cannot_authorize_ue_stop(self):
        fake={"verified":True,"empty":True,"running":0,"pending":0}
        result=build_plan("stop",CFG,FakeClient("Running"),
                          queue_check=lambda _:fake)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"],"ue_worker_readiness_not_verified")

    def test_ue_worker_readiness_cannot_use_legacy_endpoint(self):
        state=get_queue_state({**CFG,"DIRECTOR_GPU_MCP_URL":"https://legacy.invalid"})
        self.assertFalse(state["verified"])
        self.assertEqual(state["reason"],"ue_worker_readiness_not_verified")

    def test_verified_windows_worker_idle_allows_stop(self):
        import io
        from datetime import datetime,timezone
        from power_ops import UE_WORKER_POWER_URL
        data={"kind":"director_ue_windows_power_readiness_v1",
              "node_id":"ue-worker-01","platform":"Windows",
              "checked_at":datetime.now(timezone.utc).isoformat(),
              "ok":True,"verified":True,"safe_to_stop":True,
              "active_job_id":None,"unreal_process_count":0,
              "process_inventory_verified":True}
        captured=[]
        class Reply(io.BytesIO):
            status=200
            def geturl(self): return UE_WORKER_POWER_URL
        def opener(req,timeout):
            captured.append((req.full_url,req.headers.get("Authorization")))
            return Reply(json.dumps(data).encode())
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"token"
            file.write_text("a"*64,encoding="ascii")
            file.chmod(0o640)
            state=get_queue_state(CFG,opener=opener,token_file=str(file))
        self.assertTrue(state["verified"])
        self.assertTrue(state["empty"])
        self.assertEqual(state["source"],"ue_worker")
        self.assertEqual(captured,[(UE_WORKER_POWER_URL,"Bearer "+"a"*64)])
        plan=build_plan("stop",CFG,FakeClient("Running"),queue_check=lambda _:state)
        self.assertTrue(plan["allowed"])
        self.assertTrue(plan["ue_workload_verified"])

    def test_ue_worker_active_job_or_process_blocks_stop(self):
        import io
        from datetime import datetime,timezone
        from power_ops import UE_WORKER_POWER_URL
        data={"kind":"director_ue_windows_power_readiness_v1",
              "node_id":"ue-worker-01","platform":"Windows",
              "checked_at":datetime.now(timezone.utc).isoformat(),
              "ok":True,"verified":True,"safe_to_stop":False,
              "active_job_id":"a"*32,"unreal_process_count":1,
              "process_inventory_verified":True}
        class Reply(io.BytesIO):
            status=200
            def geturl(self): return UE_WORKER_POWER_URL
        def opener(req,timeout):
            return Reply(json.dumps(data).encode())
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"token"
            file.write_text("a"*64,encoding="ascii")
            file.chmod(0o600)
            state=get_queue_state(CFG,opener=opener,token_file=str(file))
        self.assertTrue(state["verified"])
        self.assertFalse(state["empty"])
        plan=build_plan("stop",CFG,FakeClient("Running"),queue_check=lambda _:state)
        self.assertEqual(plan["reason"],"ue_worker_busy")

    def test_ue_worker_spoofed_readiness_never_unlocks_stop(self):
        import io
        from datetime import datetime,timezone,timedelta
        from power_ops import UE_WORKER_POWER_URL
        base={"kind":"director_ue_windows_power_readiness_v1",
              "node_id":"ue-worker-01","platform":"Windows",
              "checked_at":datetime.now(timezone.utc).isoformat(),
              "ok":True,"verified":True,"safe_to_stop":True,
              "active_job_id":None,"unreal_process_count":0,
              "process_inventory_verified":True}
        class Reply(io.BytesIO):
            status=200
            def geturl(self):return UE_WORKER_POWER_URL
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"token"
            file.write_text("f"*64,encoding="ascii")
            file.chmod(0o600)
            invalid=[
                {"node_id":"wrong-worker"},
                {"platform":"Linux"},
                {"process_inventory_verified":False},
                {"safe_to_stop":False},
                {"active_job_id":"b"*32},
                {"unreal_process_count":1},
                {"checked_at":(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()},
                {"unreal_process_count":True},
            ]
            for delta in invalid:
                data={**base,**delta}
                state=get_queue_state(
                    CFG,token_file=str(file),
                    opener=lambda req,timeout:Reply(json.dumps(data).encode()))
                self.assertFalse(state["verified"],delta)
            # A redirect off localhost is forbidden even with valid JSON.
            class Redirect(Reply):
                def geturl(self): return "https://evil.example.test/"
            state=get_queue_state(
                CFG,token_file=str(file),
                opener=lambda req,timeout:Redirect(json.dumps(base).encode()))
            self.assertFalse(state["verified"])

    def test_power_service_reads_private_worker_credential_copy(self):
        import io
        from datetime import datetime,timezone
        from power_ops import UE_WORKER_POWER_URL
        class Reply(io.BytesIO):
            status=200
            def geturl(self):return UE_WORKER_POWER_URL
        sample={"ok":True,"verified":True,"process_inventory_verified":True,
                "kind":"director_ue_windows_power_readiness_v1",
                "node_id":"ue-worker-01","platform":"Windows",
                "unreal_process_count":0,"active_job_id":None,
                "safe_to_stop":True,
                "checked_at":datetime.now(timezone.utc).isoformat()}
        with tempfile.TemporaryDirectory() as td:
            credential=Path(td)/"ueworkertoken"
            credential.write_text("d"*64,encoding="ascii")
            credential.chmod(0o400)
            with patch.dict(os.environ,{"CREDENTIALS_DIRECTORY":td}):
                result=get_queue_state(CFG,opener=lambda req,timeout:
                                       Reply(json.dumps(sample).encode()))
        self.assertEqual(result["source"],"ue_worker")
        self.assertTrue(result["empty"])

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
