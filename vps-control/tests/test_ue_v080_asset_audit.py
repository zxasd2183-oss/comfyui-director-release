"""V0.8 Hub -> fixed EP01 Worker native-asset audit RPC: no user paths."""
from __future__ import annotations
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc


def studio(tool,args):
    assert tool == "get_production_episode"
    assert args == {"project_id":"WaitingOffice","episode_id":"EP01"}
    shots=[{"shot_id":"%02d"%i,"ordinal":i,
            "duration_ms":10000 if i==31 else 5000} for i in range(1,32)]
    return {"ok":True,"shot_count":31,"shots_truncated":False,"shots":shots}


class UEAssetAuditRpcTests(unittest.TestCase):
    def test_only_frozen_ep01_plan_reaches_worker(self):
        received=[]
        def fake_worker(path,method,body,opener,token_file):
            received.append((path,method,body))
            return {"ok":True,"job_id":"a"*32,"state":"queued"}
        with patch.dict("os.environ",{"DIRECTOR_UE_WORKER_ENABLED":"1"}),patch.object(
            ue_worker_rpc,"_v2_request",side_effect=fake_worker):
            result=ue_worker_rpc.enqueue_ue_asset_audit(
                "WaitingOffice","EP01",studio_getter=studio)
        self.assertTrue(result["ok"])
        self.assertEqual(len(received),1)
        path,method,body=received[0]
        self.assertEqual((path,method),("/v2/jobs","POST"))
        self.assertEqual(set(body),{"task","project_id","episode_id",
                                    "fps","shots","expected_total_ms"})
        self.assertEqual(body["task"],"audit_ep01_assets")
        self.assertEqual(body["expected_total_ms"],160000)
        self.assertEqual(len(body["shots"]),31)
        self.assertNotIn("path",json.dumps(body))
        self.assertNotIn("script",json.dumps(body))

    def test_invalid_episode_never_contacts_studio_or_worker(self):
        with patch.object(ue_worker_rpc,"_v2_request") as caller:
            response=ue_worker_rpc.enqueue_ue_asset_audit(
                "../bad","EP01",studio_getter=lambda *_:self.fail("studio_called"))
        self.assertEqual(response["reason"],"asset_audit_requires_locked_ep01")
        caller.assert_not_called()


if __name__=="__main__":unittest.main()
