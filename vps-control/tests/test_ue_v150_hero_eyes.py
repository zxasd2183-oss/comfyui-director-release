"""Studio-locked GPT identity gates before creating an iris candidate."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc as rpc


def registered(_tool,args):
    assert args=={"project_id":"WaitingOffice"}
    return {"ok":True,"characters":[{
        "character_id":"CHAR_GPT","revision":2,"master":None,
        "design_language":"深栗色齐颈短发 琥珀棕色眼睛"}]}


def episode(_tool,args):
    assert args=={"project_id":"WaitingOffice","episode_id":"EP01"}
    return {"ok":True,"shot_count":31,"shots_truncated":False,
            "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                      "duration_ms":10000 if i==31 else 5000}
                     for i in range(1,32)]}


class AmberEyesRpcTests(unittest.TestCase):
    def test_takes_only_episode_identifiers_and_studio_shots(self):
        sent=[]
        def submit(path,method,body,opener,token_file):
            sent.append((path,method,body))
            return {"ok":True,"job_id":"3"*32}
        with patch.dict("os.environ",{"DIRECTOR_UE_WORKER_ENABLED":"1"}), \
             patch.object(rpc,"_v2_request",side_effect=submit):
            item=rpc.enqueue_ue_hero_amber_eyes(
                "WaitingOffice","EP01",studio_getter=episode,cast_getter=registered)
        self.assertTrue(item["ok"])
        self.assertEqual(sent[0][:2],("/v2/jobs","POST"))
        self.assertEqual(sent[0][2]["task"],"build_ep01_hero_amber_eyes")
        self.assertEqual(set(sent[0][2]),{"task","project_id","episode_id",
                                          "fps","shots","expected_total_ms"})
        self.assertNotIn("script",json.dumps(sent[0][2]))
        self.assertNotIn("color",json.dumps(sent[0][2]))

    def test_refuses_nonmatching_gpt_brief(self):
        bad={"ok":True,"characters":[{"character_id":"CHAR_GPT",
                                        "revision":2,"master":None,
                                        "design_language":"blue eyes black hair"}]}
        with patch.object(rpc,"_v2_request") as sender:
            result=rpc.enqueue_ue_hero_amber_eyes(
                "WaitingOffice","EP01",studio_getter=episode,
                cast_getter=lambda *_:bad)
        self.assertEqual(result["reason"],"hero_eye_identity_lock_failed")
        sender.assert_not_called()


if __name__=="__main__":
    unittest.main()
