"""V0.9 private Hub -> Worker scene build; fixed Studio identities only."""
from __future__ import annotations
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc


def episode(tool,args):
    assert tool=="get_production_episode"
    assert args=={"project_id":"WaitingOffice","episode_id":"EP01"}
    return {"ok":True,"shot_count":31,"shots_truncated":False,
            "shots":[{"shot_id":f"{n:02}","ordinal":n,
                      "duration_ms":10000 if n==31 else 5000}
                     for n in range(1,32)]}


def scenes(tool,args):
    assert tool=="get_production_scenes"
    assert args=={"project_id":"WaitingOffice"}
    return {"ok":True,"scenes":[
        {"scene_id":"SCN-HALL","status":"draft","revision":1},
        {"scene_id":"SCN-ENTRANCE","status":"draft","revision":1},
    ]}


class UESceneBridgeTests(unittest.TestCase):
    def test_submit_fixed_studio_shots_and_scene_ids(self):
        submitted=[]
        def request(path,method,body,opener,token_file):
            submitted.append((path,method,body))
            return {"ok":True,"job_id":"a"*32,"state":"queued"}
        with patch.dict("os.environ",{"DIRECTOR_UE_WORKER_ENABLED":"1"}),patch.object(
             ue_worker_rpc,"_v2_request",side_effect=request):
            result=ue_worker_rpc.enqueue_ue_scene_candidates(
                "WaitingOffice","EP01",studio_getter=episode,scene_getter=scenes)
        self.assertTrue(result["ok"])
        self.assertEqual(len(submitted),1)
        path,method,body=submitted[0]
        self.assertEqual((path,method),("/v2/jobs","POST"))
        self.assertEqual(body["task"],"build_ep01_scene_candidates")
        self.assertEqual((body["project_id"],body["episode_id"]),
                         ("WaitingOffice","EP01"))
        self.assertEqual((body["fps"],body["expected_total_ms"]),(24,160000))
        self.assertEqual(len(body["shots"]),31)
        self.assertEqual(set(body),{"task","project_id","episode_id",
                                     "fps","expected_total_ms","shots"})
        self.assertNotIn("path",json.dumps(body))
        self.assertNotIn("script",json.dumps(body))

    def test_deny_unknown_episode_before_any_studio_or_network_call(self):
        with patch.object(ue_worker_rpc,"_v2_request") as sender:
            out=ue_worker_rpc.enqueue_ue_scene_candidates(
                "Wrong","EP01",
                studio_getter=lambda *_:self.fail("unexpected studio query"),
                scene_getter=lambda *_:self.fail("unexpected scene query"))
        self.assertEqual(out["reason"],"scene_candidates_require_locked_ep01")
        sender.assert_not_called()

    def test_missing_scene_registry_fails_closed(self):
        with patch.object(ue_worker_rpc,"_v2_request") as sender:
            out=ue_worker_rpc.enqueue_ue_scene_candidates(
                "WaitingOffice","EP01",studio_getter=episode,
                scene_getter=lambda *_:{"ok":True,"scenes":[
                    {"scene_id":"SCN-HALL","status":"draft"}]})
        self.assertEqual(out["reason"],"studio_scene_drafts_missing")
        sender.assert_not_called()


if __name__=="__main__":
    unittest.main()
