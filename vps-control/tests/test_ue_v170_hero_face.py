"""Stable Director task allowlist and frozen Studio facial sculpt contract."""
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
        "character_id":"CHAR_GPT","revision":2,"master":None,"role":"main",
        "design_language":"深栗色 齐颈侧分短发 琥珀棕色眼睛 象牙白外套 青绿细节"
    }]}


def episode(name,args):
    assert (name,args)==("get_production_episode",{
        "project_id":"WaitingOffice","episode_id":"EP01"})
    return {"ok":True,"shot_count":31,"shots_truncated":False,
            "shots":[{"shot_id":f"{i:02d}","ordinal":i,
                      "duration_ms":10000 if i==31 else 5000}
                     for i in range(1,32)]}


class V170FaceRpcTests(unittest.TestCase):
    def test_one_locked_sculpt_plan_from_studio(self):
        calls=[]
        def send(path,method,body,opener,token_file):
            calls.append((path,method,body))
            return {"ok":True,"job_id":"1"*32,"state":"queued"}
        with patch.dict("os.environ",{"DIRECTOR_UE_WORKER_ENABLED":"1"}), \
             patch.object(rpc,"_v2_request",side_effect=send):
            answer=rpc.enqueue_ue_hero_face_contour(
                "WaitingOffice","EP01",studio_getter=episode,
                cast_getter=characters)
        self.assertTrue(answer["ok"])
        self.assertEqual(calls[0][:2],("/v2/jobs","POST"))
        self.assertEqual(calls[0][2]["task"],"build_ep01_hero_face_contour")
        self.assertEqual(set(calls[0][2]),{
            "task","project_id","episode_id","fps","shots",
            "expected_total_ms"})
        self.assertNotIn("asset_path",json.dumps(calls[0][2]))
        self.assertNotIn("landmarks",json.dumps(calls[0][2]))
        self.assertNotIn("script",json.dumps(calls[0][2]))

    def test_studio_master_or_wrong_id_blocks_worker(self):
        with patch.object(rpc,"_v2_request") as send:
            bad=rpc.enqueue_ue_hero_face_contour("WaitingOffice","EP02")
            self.assertFalse(bad["ok"])
            approved={"ok":True,"characters":[{
                "character_id":"CHAR_GPT","revision":2,
                "master":"approved","role":"main",
                "design_language":"深栗色 琥珀 象牙白 青绿"}]}
            bad=rpc.enqueue_ue_hero_face_contour(
                "WaitingOffice","EP01",studio_getter=episode,
                cast_getter=lambda *_:approved)
            self.assertEqual(bad["reason"],"hero_face_studio_lock_failed")
        send.assert_not_called()

    def test_stable_task_entry_denies_unknown_and_wrong_episode(self):
        self.assertEqual(
            hub_app.submit_director_task("execute_shell","WaitingOffice","EP01"),
            {"ok":False,"reason":"director_task_not_allowlisted"})
        self.assertEqual(
            hub_app.submit_director_task("hero_face_contour_v1","WaitingOffice","EP02"),
            {"ok":False,"reason":"director_task_requires_locked_ep01"})
        self.assertEqual(set(hub_app.DIRECTOR_TASK_ALLOWLIST),{
            "hero_face_contour_v1","hero_amber_eyes_v1",
            "hero_runtime_audit_v1","hero_full_face_rig_v1"})
        with patch.dict(hub_app.DIRECTOR_TASK_ALLOWLIST,{
            "hero_face_contour_v1":lambda p,e:{"ok":True,"task":"face",
                                               "project_id":p,"episode_id":e}}):
            response=hub_app.submit_director_task("hero_face_contour_v1",
                                                   "WaitingOffice","EP01")
        self.assertTrue(response["ok"])
        self.assertEqual(response["task"],"face")


if __name__=="__main__":
    unittest.main()
