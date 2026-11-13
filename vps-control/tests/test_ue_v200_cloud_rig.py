"""Epic cloud rig request remains Studio-locked behind stable Hub task API."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hub_app
import ue_worker_rpc as rpc


def characters(name,args):
    assert (name,args)==("get_project_characters",{"project_id":"WaitingOffice"})
    return {"ok":True,"characters":[{
        "character_id":"CHAR_GPT","revision":2,"role":"main","master":None,
        "design_language":"深栗色短发，琥珀棕眼，象牙白外套，青绿点缀"}]}


def episode(name,args):
    assert (name,args)==("get_production_episode",{
        "project_id":"WaitingOffice","episode_id":"EP01"})
    return {"ok":True,"shot_count":31,"shots_truncated":False,
            "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                      "duration_ms":10000 if i==31 else 5000}
                     for i in range(1,32)]}


class CloudRigRPCTests(unittest.TestCase):
    def test_frozen_inputs_no_arbitrary_cloud_params(self):
        submitted=[]
        def send(path,method,body,opener,token_file):
            submitted.append((path,method,body))
            return {"ok":True,"job_id":"f"*32,"state":"queued"}
        with patch.dict("os.environ",{"DIRECTOR_UE_WORKER_ENABLED":"1"}), \
             patch.object(rpc,"_v2_request",side_effect=send):
            result=rpc.enqueue_ue_hero_cloud_rig(
                "WaitingOffice","EP01",studio_getter=episode,
                cast_getter=characters)
        self.assertTrue(result["ok"])
        self.assertEqual(submitted[0][:2],("/v2/jobs","POST"))
        sent=submitted[0][2]
        self.assertEqual(sent["task"],"build_ep01_hero_cloud_rig")
        self.assertEqual(set(sent),{"task","project_id","episode_id",
                                    "fps","shots","expected_total_ms"})
        self.assertNotIn("username",json.dumps(sent))
        self.assertNotIn("token",json.dumps(sent))
        self.assertNotIn("url",json.dumps(sent))
        self.assertNotIn("source_path",json.dumps(sent))

    def test_wrong_studio_master_fails_without_cloud_call(self):
        with patch.object(rpc,"_v2_request") as send:
            blocked=rpc.enqueue_ue_hero_cloud_rig("WaitingOffice","EP02")
            self.assertFalse(blocked["ok"])
            updated={"ok":True,"characters":[{
                "character_id":"CHAR_GPT","revision":2,"role":"main",
                "master":"approved","design_language":"深栗色 琥珀 象牙白 青绿"}]}
            blocked=rpc.enqueue_ue_hero_cloud_rig(
                "WaitingOffice","EP01",studio_getter=episode,
                cast_getter=lambda *_:updated)
            self.assertEqual(blocked["reason"],"hero_rig_studio_identity_lock_failed")
        send.assert_not_called()

    def test_v2_cloud_rig_uses_stable_tool_without_schema_change(self):
        self.assertIn("hero_full_face_rig_v1",hub_app.DIRECTOR_TASK_ALLOWLIST)
        self.assertNotIn("execute_shell",hub_app.DIRECTOR_TASK_ALLOWLIST)


if __name__=="__main__":
    unittest.main()
