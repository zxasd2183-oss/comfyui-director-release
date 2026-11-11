"""Signed Studio brain scene drafts and per-shot readiness (no GPU calls)."""
from contextlib import closing
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import studio_brain as brain
import production_core as core
import production_workflows as workflows
import scene_library as scenes
import visual_library as visuals
import character_library as characters
import shot_character_bindings as bindings


def draft(project="WaitingOffice", scene_id="SCN_HALL"):
    return {
        "project_id":project, "scene_id":scene_id,
        "display_name":"事务所大厅",
        "scene_type":"interior",
        "layout_notes":"浅奶白与薄荷绿，木桌、书架、落地窗及控制终端；空景母版待审核。",
        "lighting_notes":"自然窗光与柔和台灯，警报段另设红色警示光。",
        "camera_rules":"入口和大厅共用连续空间轴线，保持31镜头轴向一致。",
        "continuity_rules":"门与桌的相对位置固定，不镜像人物右手红绳。",
        "scene_notes":"原创日系2D动画；不使用品牌Logo、字幕或场景内文字。",
    }


class EpisodeSceneBrainTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db=str(Path(tmp.name)/"production.sqlite")
        with closing(core.open_db(self.db)) as db:
            visuals.prepare_schema(db)
            characters.prepare_schema(db)
            scenes.prepare_schema(db)
            bindings.prepare_schema(db)
            workflows.prepare_schema(db)
            for project in ("WaitingOffice","OtherProject"):
                core.create_project(db,project,"project")
                core.create_episode(db,project,"EP01","episode",1)
                core.create_shot(db,project,"EP01","01",1,3000)

    def test_create_draft_read_catalog_and_no_approval(self):
        result=brain.execute(self.db,"create_production_scene",draft())
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"],"draft")
        self.assertFalse(result["gpu_action"])
        catalog=brain.execute(self.db,"get_production_scenes",{"project_id":"WaitingOffice"})
        self.assertEqual(len(catalog["scenes"]),1)
        record=catalog["scenes"][0]
        self.assertEqual(record["scene_id"],"SCN_HALL")
        self.assertEqual(record["status"],"draft")
        self.assertIsNone(record["approved_revision"])
        self.assertIsNone(record["approved_visual_id"])
        self.assertEqual(record["candidate_visual_count"],0)
        self.assertNotIn("layout_notes",record) # bounded metadata, not media or full profile
        self.assertFalse(catalog["gpu_action"])
        with closing(core.open_db(self.db,initialize=False)) as db:
            self.assertTrue(core.verify_chain(db))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM scene_review_events").fetchone()[0],0)

    def test_duplicate_scene_is_rejected_and_cross_project_isolated(self):
        brain.execute(self.db,"create_production_scene",draft())
        with self.assertRaises(brain.BrainError) as error:
            brain.execute(self.db,"create_production_scene",draft())
        self.assertEqual(error.exception.reason,"scene_already_exists")
        self.assertEqual(brain.execute(self.db,"get_production_scenes",
                         {"project_id":"OtherProject"})["scenes"],[])

    def test_readiness_reports_actual_missing_upstreams(self):
        result=brain.execute(self.db,"get_production_episode_readiness",
                             {"project_id":"WaitingOffice","episode_id":"EP01"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["shot_count"],1)
        self.assertEqual(result["approved_take_count"],0)
        self.assertFalse(result["runner_connected"])
        self.assertEqual(result["shots"][0]["video_take_status"],"not_imported")
        self.assertIn("shot_plans_not_approved",result["shots"][0]["upstream_blockers"])
        self.assertIn("project_spec_not_approved",result["shots"][0]["upstream_blockers"])
        self.assertFalse(result["shots"][0]["upstream_ready"])

    def test_refuse_hidden_approval_and_unexpected_fields(self):
        with self.assertRaises(brain.BrainError) as error:
            brain.execute(self.db,"create_production_scene",
                          {**draft(),"approved":True})
        self.assertEqual(error.exception.reason,"invalid_brain_arguments")
        with self.assertRaises(brain.BrainError):
            brain.execute(self.db,"approve_production_scene",draft())
        with self.assertRaises(brain.BrainError):
            brain.execute(self.db,"get_production_scenes",{"project_id":"WaitingOffice","extra":"x"})

    def test_invalid_scene_id_and_empty_layout_fail_closed(self):
        for inputs in ({**draft(),"scene_id":"../../secret"},
                       {**draft(),"layout_notes":""}):
            with self.assertRaises(brain.BrainError):
                brain.execute(self.db,"create_production_scene",inputs)


if __name__=="__main__":
    unittest.main()
