"""V1.3 single GPT MetaHuman seed task, fixed to Studio rev2 and EP01."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc as rpc


def cast(_tool, args):
    assert args == {"project_id":"WaitingOffice"}
    return {"ok":True,"characters":[{
        "character_id":"CHAR_GPT","role":"main","revision":2,"master":None,
        "design_language":"深栗色短发 琥珀眼睛 象牙白外套 青绿内衬"
    }]}


def episode(_tool,args):
    assert args=={"project_id":"WaitingOffice","episode_id":"EP01"}
    return {"ok":True,"shot_count":31,"shots_truncated":False,
            "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                      "duration_ms":10000 if i==31 else 5000}
                     for i in range(1,32)]}


class GptSeedRpcTests(unittest.TestCase):
    def test_fixed_identity_and_unchanged_studio_shots_only(self):
        sent=[]
        def sender(path,method,body,opener,token_file):
            sent.append((path,method,body))
            return {"ok":True,"state":"queued","job_id":"f"*32}
        with patch.dict("os.environ",{"DIRECTOR_UE_WORKER_ENABLED":"1"}), \
             patch.object(rpc,"_v2_request",side_effect=sender):
            value=rpc.enqueue_ue_hero_metahuman_seed(
                "WaitingOffice","EP01",studio_getter=episode,cast_getter=cast)
        self.assertTrue(value["ok"])
        self.assertEqual(len(sent),1)
        self.assertEqual(sent[0][:2],("/v2/jobs","POST"))
        self.assertEqual(sent[0][2]["task"],"build_ep01_hero_metahuman_seed")
        self.assertEqual((len(sent[0][2]["shots"]),sent[0][2]["fps"],
                          sent[0][2]["expected_total_ms"]),(31,24,160000))
        self.assertEqual(set(sent[0][2]),{"task","project_id","episode_id",
                                           "fps","shots","expected_total_ms"})
        self.assertNotIn("script",json.dumps(sent[0][2]))
        self.assertNotIn("paths",json.dumps(sent[0][2]))

    def test_rejects_wrong_episode_before_network(self):
        with patch.object(rpc,"_v2_request") as sender:
            value=rpc.enqueue_ue_hero_metahuman_seed(
                "WaitingOffice","EP02",studio_getter=episode,cast_getter=cast)
        self.assertFalse(value["ok"])
        sender.assert_not_called()

    def test_rejects_inconsistent_identity_or_existing_master(self):
        for edits in ({"revision":1},{"master":"approved"},
                      {"design_language":"red hair green eyes"}):
            bad=cast("get_project_characters",{"project_id":"WaitingOffice"})
            bad["characters"][0].update(edits)
            with patch.object(rpc,"_v2_request") as sender:
                value=rpc.enqueue_ue_hero_metahuman_seed(
                    "WaitingOffice","EP01",studio_getter=episode,
                    cast_getter=lambda *_:bad)
            self.assertFalse(value["ok"])
            self.assertEqual(value["reason"],"hero_studio_design_lock_not_verified")
            sender.assert_not_called()


if __name__=="__main__":
    unittest.main()
