"""V1.0 Hub -> Worker EP01 5-actress original Blueprint build gate."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc


def cast(tool,args):
    assert tool=="get_project_characters"
    assert args=={"project_id":"WaitingOffice"}
    return {"ok":True,"characters":[
        {"character_id":ident,"role":"main","master":None}
        for ident in ("CHAR_GPT","CHAR_GEM","CHAR_DS","CHAR_CLA","CHAR_ZERO")
    ] + [{"character_id":"CHAR_QWEN","role":"extended","master":None}]}


def episode(tool,args):
    assert tool=="get_production_episode"
    assert args=={"project_id":"WaitingOffice","episode_id":"EP01"}
    return {"ok":True,"shot_count":31,"shots_truncated":False,
            "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                      "duration_ms":10000 if i==31 else 5000}
                     for i in range(1,32)]}


class CastRpcTests(unittest.TestCase):
    def test_exact_five_main_cast_from_studio(self):
        sent=[]
        def post(path,method,body,opener,token_file):
            sent.append((path,method,body))
            return {"ok":True,"state":"queued","job_id":"a"*32}
        with patch.dict("os.environ",{"DIRECTOR_UE_WORKER_ENABLED":"1"}),patch.object(
                ue_worker_rpc,"_v2_request",side_effect=post):
            o=ue_worker_rpc.enqueue_ue_cast_blueprints(
                "WaitingOffice","EP01",studio_getter=episode,cast_getter=cast)
        self.assertTrue(o["ok"])
        self.assertEqual(len(sent),1)
        self.assertEqual(sent[0][:2],("/v2/jobs","POST"))
        body=sent[0][2]
        self.assertEqual(body["task"],"build_ep01_cast_blueprints")
        self.assertEqual((len(body["shots"]),body["expected_total_ms"]),(31,160000))
        self.assertEqual(set(body),{"task","project_id","episode_id",
                                    "fps","shots","expected_total_ms"})
        self.assertNotIn("script",json.dumps(body))
        self.assertNotIn("asset",json.dumps(body))
        self.assertNotIn("path",json.dumps(body))

    def test_wrong_episode_no_studio_or_worker_call(self):
        with patch.object(ue_worker_rpc,"_v2_request") as request:
            o=ue_worker_rpc.enqueue_ue_cast_blueprints(
                "WaitingOffice","EP02",
                cast_getter=lambda *_:self.fail("unsafe query"))
        self.assertEqual(o["reason"],"cast_requires_locked_ep01")
        request.assert_not_called()

    def test_missing_or_extra_main_cast_fails_before_worker(self):
        with patch.object(ue_worker_rpc,"_v2_request") as sender:
            o=ue_worker_rpc.enqueue_ue_cast_blueprints(
                "WaitingOffice","EP01",studio_getter=episode,
                cast_getter=lambda *_:{"ok":True,"characters":[
                    {"character_id":"CHAR_GPT","role":"main"}]})
        self.assertEqual(o["reason"],"studio_main_cast_registry_mismatch")
        sender.assert_not_called()


if __name__=="__main__":unittest.main()
