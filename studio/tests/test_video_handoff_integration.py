"""Studio audited DB -> real handoff JSON -> GPU local planner.

Offline integration: no VPS requests, no H3 access, no GPU power or /prompt.
"""
import base64
from contextlib import closing
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT.parent/"video-pipeline"))
import production_core as core
import production_workflows as work
import visual_library as visuals
import scene_library as scenes
import character_library as chars
import character_library_v2 as charv2
import shot_character_bindings as bindings
import director_video as runner

PNG=bytes.fromhex(
 "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
 "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")


class StudioToGpuHandoffTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db=str(Path(temp.name)/"production.sqlite")
        with closing(core.open_db(self.db)) as db:
            for module in (visuals,scenes,chars,charv2,bindings,work):
                module.prepare_schema(db)
            core.create_project(db,"WaitingOffice","待回答事务所")
            core.create_episode(db,"WaitingOffice","EP01","第一集",1)
            core.create_shot(db,"WaitingOffice","EP01","01",1,3000)

    def upload(self,kind,subject):
        return visuals.upload_visual(self.db,{
            "project_id":"WaitingOffice","episode_id":"EP01",
            "kind":kind,"subject_id":subject,"filename":"verified.png",
            "image_base64":base64.b64encode(PNG).decode()
        },"studio_test")["visual_id"]

    def save(self,kind,fields,visual=None,revision=0):
        return work.save_unit(self.db,{
            "project_id":"WaitingOffice",
            "episode_id":"EP01" if kind!="props" else "",
            "kind":kind,"unit_id":"SPEC" if kind=="settings" else "01",
            "shot_id":"01" if kind in work.SHOT_KINDS else "",
            "expected_revision":revision,"fields":fields,
            "note":"实际跨模块离线契约测试",
            "source_visual_id":visual},"studio_test")

    def review(self,kind,action,revision=1):
        return work.review_unit(self.db,{
            "project_id":"WaitingOffice","episode_id":"EP01",
            "kind":kind,"unit_id":"SPEC" if kind=="settings" else "01",
            "expected_revision":revision,"decision":action,
            "rationale":"人工核对来源、连续性与版本完整，允许进入下一阶段。"
        },"studio_test")

    def build_approved_chain(self):
        scenes.create_scene(self.db,{
            "project_id":"WaitingOffice","scene_id":"SCN_HALL",
            "display_name":"事务所大厅","scene_type":"interior",
            "layout_notes":"门窗和长桌固定",
            "lighting_notes":"窗侧光","camera_rules":"不越过轴线",
            "continuity_rules":"家具保持位置","scene_notes":"固定场景"
        },"studio_test")
        pic=self.upload("scene","SCN_HALL")
        scenes.link_scene_visual(self.db,{"project_id":"WaitingOffice",
            "scene_id":"SCN_HALL","visual_id":pic,"reference_type":"overview"},
            "studio_test")
        for action in ("submit","approve"):
            scenes.review_scene(self.db,{"project_id":"WaitingOffice",
                "scene_id":"SCN_HALL","expected_revision":1,
                "decision":action,"visual_id":pic if action=="approve" else None,
                "rationale":"人工核对空间布局和场景来源真实有效。"},"studio_test")
        self.save("settings",{"aspect":"9:16","width":"1080",
            "height":"1920","fps":"24"})
        self.review("settings","submit")
        self.review("settings","approve")
        self.save("shot_plans",{"title":"第一镜","scene_id":"SCN_HALL",
            "story":"拍桌纸张震动"})
        self.review("shot_plans","submit")
        self.review("shot_plans","approve")
        board=self.upload("storyboard","01")
        self.save("storyboards",{"composition":"正面固定机位"},board)
        self.review("storyboards","submit")
        self.review("storyboards","approve")
        self.save("white_models",{"stage_width":"9","stage_depth":"10",
            "camera_z":"2.2","focal_mm":"35","actor_height":"1.7",
            "quality":"粗白模"})
        self.review("white_models","submit")
        self.review("white_models","approve")
        self.save("video_plans",{"model":"H3 API workflow",
            "prompt":"桌面上的纸张轻轻弹起，镜头稳定","fps":"24",
            "width":"1080","height":"1920","duration":"3","seed":"1234"})
        self.review("video_plans","submit")

    def test_real_studio_package_accepted_by_local_gpu_planner(self):
        self.build_approved_chain()
        package=work.get_video_handoff_package(
            self.db,"WaitingOffice","EP01","01")
        self.assertEqual(package["package"]["blockers"],
                         ["video_render_executor_not_connected"])
        self.assertFalse(package["package"]["gpu_dispatch_authorized"])
        workflow={
            "6":{"class_type":"TextNode","inputs":{"text":""}},
            "9":{"class_type":"H3Frames","inputs":{"frames":72,"seed":1}}}
        mapping={"prompt":{"node":"6","input":"text"},
                 "frames":{"node":"9","input":"frames"},
                 "seed":{"node":"9","input":"seed"}}
        plan=runner.build_studio_handoff_plan(package,workflow,mapping)
        self.assertEqual(plan["shot_count"],1)
        self.assertEqual(plan["jobs"][0]["frames"],72)
        self.assertEqual(plan["jobs"][0]["graph"]["6"]["inputs"]["text"],
                         "桌面上的纸张轻轻弹起，镜头稳定")
        self.assertEqual(plan["studio_handoff"]["package_sha256"],
                         package["package_sha256"])
        self.assertFalse(plan["gpu_actions_performed"])
        with closing(core.open_db(self.db,initialize=False)) as db:
            self.assertTrue(core.verify_chain(db))

    def test_revised_upstream_blocks_video_import_without_approval(self):
        self.build_approved_chain()
        self.save("shot_plans",{"title":"需要重新审阅的镜头",
            "scene_id":"SCN_HALL"},revision=1)
        package=work.get_video_handoff_package(
            self.db,"WaitingOffice","EP01","01")
        self.assertIn("shot_plans_not_approved",package["package"]["blockers"])
        with self.assertRaisesRegex(runner.PlanError,"upstream approvals incomplete"):
            runner.build_studio_handoff_plan(package,
                {"6":{"class_type":"TextNode","inputs":{"text":""}}},
                {"prompt":{"node":"6","input":"text"}})


if __name__=="__main__":
    unittest.main()
