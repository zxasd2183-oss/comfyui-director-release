"""Studio-gated GPT MetaHuman runtime audit over narrow Worker RPC."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc as rpc


def character(_tool,args):
    assert args=={"project_id":"WaitingOffice"}
    return {"ok":True,"characters":[{"character_id":"CHAR_GPT",
                                     "revision":2,"master":None}]}


def episode(_tool,args):
    assert args=={"project_id":"WaitingOffice","episode_id":"EP01"}
    return {"ok":True,"shot_count":31,"shots_truncated":False,
            "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                      "duration_ms":10000 if i==31 else 5000}
                     for i in range(1,32)]}


class HeroRuntimeRpcTests(unittest.TestCase):
    def test_fixed_audit_spec_uses_only_studio_data(self):
        requests=[]
        def submit(path,method,body,opener,token_file):
            requests.append((path,method,body))
            return {"ok":True,"job_id":"1"*32,"state":"queued"}
        with patch.dict("os.environ",{"DIRECTOR_UE_WORKER_ENABLED":"1"}), \
             patch.object(rpc,"_v2_request",side_effect=submit):
            item=rpc.enqueue_ue_hero_runtime_audit(
                "WaitingOffice","EP01",studio_getter=episode,cast_getter=character)
        self.assertTrue(item["ok"])
        self.assertEqual(requests[0][:2],("/v2/jobs","POST"))
        self.assertEqual(requests[0][2]["task"],"audit_ep01_hero_metahuman_runtime")
        self.assertEqual(set(requests[0][2]),{"project_id","episode_id","task",
                                              "fps","shots","expected_total_ms"})
        self.assertNotIn("script",json.dumps(requests[0][2]))
        self.assertNotIn("asset_path",json.dumps(requests[0][2]))

    def test_wrong_episode_never_calls_worker(self):
        with patch.object(rpc,"_v2_request") as send:
            item=rpc.enqueue_ue_hero_runtime_audit("WaitingOffice","EP02")
        self.assertFalse(item["ok"])
        send.assert_not_called()

    def test_identity_must_remain_unapproved(self):
        wrong={"ok":True,"characters":[{"character_id":"CHAR_GPT",
                                        "revision":2,"master":"approved"}]}
        with patch.object(rpc,"_v2_request") as send:
            item=rpc.enqueue_ue_hero_runtime_audit(
                "WaitingOffice","EP01",studio_getter=episode,
                cast_getter=lambda *_:wrong)
        self.assertEqual(item["reason"],"hero_studio_identity_not_locked")
        send.assert_not_called()


if __name__=="__main__":
    unittest.main()
