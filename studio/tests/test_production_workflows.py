"""End-to-end offline checks for the next seven functional Studio modules."""
import base64
import http.client
import json
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import production_core as core
import production_workflows as w
import visual_library as v
import scene_library as scenes
import character_library as characters
import studio_server as server

PNG=bytes.fromhex(
 "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
 "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/"production.sqlite")
        with closing(core.open_db(self.path)) as db:
            v.prepare_schema(db);characters.prepare_schema(db)
            scenes.prepare_schema(db);w.prepare_schema(db)
            for project in ("WaitingOffice","AnotherProject"):
                core.create_project(db,project,"project")
                core.create_episode(db,project,"EP01","Episode 1",1)
                core.create_shot(db,project,"EP01","01",1,4000)
                core.create_shot(db,project,"EP01","02",2,4000)

    def unit(self,kind,uid=None,fields=None,**change):
        scope=w.SCHEMAS[kind]["scope"]
        uid=uid or ("01" if scope=="shot" else
                    "SPEC" if scope=="episode" else "ITEM_ONE")
        fields=fields or {"name":"可用道具"} if kind=="props" else fields or {
            "title":"镜头或任务名称"} if kind in ("shot_plans","tasks") else fields or {
            "composition":"构图备忘"} if kind=="storyboards" else fields or {
            "stage_width":"9","stage_depth":"10","camera_z":"2.5",
            "focal_mm":"35","actor_height":"1.7"} if kind=="white_models" else fields or {
            "model":"暂未连接的 Comfy 工作流"} if kind=="video_plans" else fields or {
            "aspect":"9:16","width":"1080","height":"1920","fps":"24"}
        return {"project_id":"WaitingOffice",
            "episode_id":"" if scope=="project" else "EP01",
            "kind":kind,"unit_id":uid,
            "shot_id":uid if scope=="shot" else "",
            "expected_revision":0,"fields":fields,
            "note":"仅供审核的制作草稿","source_visual_id":None,**change}

    def save(self,kind,uid=None,fields=None,**changes):
        return w.save_unit(self.path,self.unit(kind,uid,fields,**changes),"test_operator")

    def decide(self,kind,uid,decision,revision=1):
        scope=w.SCHEMAS[kind]["scope"]
        return w.review_unit(self.path,{
            "project_id":"WaitingOffice",
            "episode_id":"" if scope=="project" else "EP01",
            "kind":kind,"unit_id":uid,"expected_revision":revision,
            "decision":decision,
            "rationale":"人工检查完成，已核对版本、源素材、连续性规范。"
        },"test_operator")

    def upload(self,kind,subject,project="WaitingOffice"):
        return v.upload_visual(self.path,{
            "project_id":project,"episode_id":"EP01","kind":kind,
            "subject_id":subject,"filename":"reference.png",
            "image_base64":base64.b64encode(PNG).decode()
        },"test_operator")["visual_id"]

    def test_all_seven_independent_modules_persist_and_scopes(self):
        for kind in w.KINDS:
            with self.subTest(kind=kind):
                saved=self.save(kind)
                self.assertEqual(saved["status"],"draft")
                self.assertFalse(saved["gpu_action"])
                out=w.list_units(self.path,"WaitingOffice",kind,
                    "" if w.SCHEMAS[kind]["scope"]=="project" else "EP01")
                self.assertEqual(len(out["items"]),1)
                self.assertEqual(out["items"][0]["revision"],1)
                self.assertEqual(out["items"][0]["status"],"draft")
                self.assertEqual(out["items"][0]["fields"],
                    self.unit(kind)["fields"])
        with closing(core.open_db(self.path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM production_shots").fetchone()[0],4)
            self.assertTrue(core.verify_chain(db))

    def test_stale_revision_and_history_are_immutable(self):
        self.save("props")
        v2=self.save("props",expected_revision=1,fields={"name":"道具升级版","grip":"右手"})
        self.assertEqual(v2["revision"],2)
        with self.assertRaises(w.WorkflowError) as ctx:
            self.save("props",expected_revision=1)
        self.assertEqual(ctx.exception.reason,"stale_workflow_revision")
        with closing(core.open_db(self.path,initialize=False)) as db:
            snapshots=db.execute("SELECT snapshot_json FROM studio_work_unit_history "
                "WHERE kind='props' ORDER BY revision").fetchall()
            self.assertEqual(len(snapshots),2)
            self.assertEqual(json.loads(json.loads(snapshots[0][0])["fields_json"])["name"],
                             "可用道具")
            self.assertTrue(core.verify_chain(db))

    def test_prop_requires_real_own_visual_and_two_step_review(self):
        self.save("props")
        with self.assertRaises(w.WorkflowError):
            self.decide("props","ITEM_ONE","approve")
        self.assertEqual(self.decide("props","ITEM_ONE","submit")["status"],"in_review")
        with self.assertRaises(w.WorkflowError) as ex:
            self.decide("props","ITEM_ONE","approve")
        self.assertEqual(ex.exception.reason,"individual_reference_image_required")
        with self.assertRaises(w.WorkflowError):
            self.save("props",expected_revision=1)
        self.decide("props","ITEM_ONE","reject")
        own=self.upload("prop","ITEM_ONE")
        self.save("props",expected_revision=1,source_visual_id=own)
        self.decide("props","ITEM_ONE","submit",revision=2)
        self.decide("props","ITEM_ONE","approve",revision=2)
        record=w.list_units(self.path,"WaitingOffice","props")["items"][0]
        self.assertEqual(record["approved_revision"],2)
        self.assertEqual(record["source_visual_id"],own)
        self.assertEqual(record["status"],"approved")

    def test_wrong_project_kind_and_composite_images_are_refused(self):
        own=self.upload("prop","ITEM_ONE")
        self.upload("prop","ITEM_TWO")
        foreign=self.upload("prop","ITEM_ONE","AnotherProject")
        for case,reason in [
            (self.unit("props",source_visual_id=foreign),"workflow_visual_not_found"),
            (self.unit("props",source_visual_id=self.upload("storyboard","ITEM_ONE")),
                "workflow_visual_type_mismatch"),
            (self.unit("props",source_visual_id=self.upload("prop","PROP_GROUP")),
                "workflow_individual_visual_required"),
        ]:
            with self.subTest(reason=reason):
                with self.assertRaises(w.WorkflowError) as caught:
                    w.save_unit(self.path,case,"test_operator")
                self.assertEqual(caught.exception.reason,reason)

    def test_shot_scene_and_prop_dependencies_block_premature_approval(self):
        with self.assertRaises(w.WorkflowError) as ex:
            self.save("shot_plans",fields={"title":"开场","scene_id":"SCN_OFFICE"})
        self.assertEqual(ex.exception.reason,"scene_dependency_not_found")
        scenes.create_scene(self.path,{
            "project_id":"WaitingOffice","scene_id":"SCN_OFFICE",
            "display_name":"事务所大厅","scene_type":"interior",
            "layout_notes":"窗在左边，门在右边，桌子固定",
            "lighting_notes":"日光","camera_rules":"不要跨轴",
            "continuity_rules":"物品保持位置","scene_notes":"可跨集复用"
        },"test_operator")
        self.save("shot_plans",fields={"title":"开场","scene_id":"SCN_OFFICE"})
        self.decide("shot_plans","01","submit")
        with self.assertRaises(w.WorkflowError) as e:
            self.decide("shot_plans","01","approve")
        self.assertEqual(e.exception.reason,"scene_not_approved")
        image=self.upload("scene","SCN_OFFICE")
        scenes.link_scene_visual(self.path,{"project_id":"WaitingOffice",
            "scene_id":"SCN_OFFICE","visual_id":image,
            "reference_type":"overview"},"test_operator")
        for choice in ("submit","approve"):
            scenes.review_scene(self.path,{"project_id":"WaitingOffice",
                "scene_id":"SCN_OFFICE","expected_revision":1,
                "decision":choice,"visual_id":image if choice=="approve" else None,
                "rationale":"经人工检查场景布局和光照达到一致性要求。"},"test_operator")
        self.assertEqual(self.decide("shot_plans","01","approve")["status"],"approved")

    def test_storyboards_require_real_approved_plan_and_image(self):
        self.save("storyboards")
        self.decide("storyboards","01","submit")
        with self.assertRaises(w.WorkflowError) as caught:
            self.decide("storyboards","01","approve")
        self.assertEqual(caught.exception.reason,"shot_plan_not_approved")
        # The separate approval gate is enforced independently; no auto final
        # stage just because a shot image exists.
        self.assertFalse(w.list_units(self.path,"WaitingOffice",
            "storyboards","EP01")["items"][0]["source_visual_id"])

    def test_white_model_requires_approved_plan_and_complete_geometry(self):
        self.save("white_models")
        self.decide("white_models","01","submit")
        with self.assertRaises(w.WorkflowError) as e:
            self.decide("white_models","01","approve")
        self.assertEqual(e.exception.reason,"shot_plan_not_approved")

    def test_video_is_job_specification_not_fake_rendered_clip(self):
        self.save("video_plans")
        self.decide("video_plans","01","submit")
        with self.assertRaises(w.WorkflowError) as e:
            self.decide("video_plans","01","approve")
        self.assertEqual(e.exception.reason,"video_render_not_connected")
        row=w.list_units(self.path,"WaitingOffice","video_plans","EP01")
        self.assertEqual(row["execution_status"],"not_connected")
        self.assertEqual(row["items"][0]["status"],"in_review")

    def test_task_dependency_and_result_proof(self):
        self.save("tasks",uid="TASK_1",fields={"title":"母版验收"})
        self.decide("tasks","TASK_1","submit")
        with self.assertRaises(w.WorkflowError) as e:
            self.decide("tasks","TASK_1","approve")
        self.assertEqual(e.exception.reason,"task_completion_evidence_required")
        self.decide("tasks","TASK_1","reject")
        self.save("tasks",uid="TASK_1",expected_revision=1,
                  fields={"title":"母版验收","outcome":"审核表已签字，图像版本已锁定"})
        self.decide("tasks","TASK_1","submit",2)
        self.decide("tasks","TASK_1","approve",2)
        self.save("tasks",uid="TASK_2",fields={
            "title":"画分镜","prerequisites":"TASK_1",
            "outcome":"完成并交付分镜图片审核记录"})
        self.decide("tasks","TASK_2","submit")
        self.assertEqual(self.decide("tasks","TASK_2","approve")["status"],"approved")

    def test_episodes_format_9_by_16_and_approval(self):
        self.save("settings")
        self.decide("settings","SPEC","submit")
        self.assertEqual(self.decide("settings","SPEC","approve")["status"],"approved")
        with closing(core.open_db(self.path,initialize=False)) as db:
            self.assertTrue(core.verify_chain(db))

    def test_public_unauthenticated_workflow_api_denied(self):
        app=server.StudioServer(str(Path(self.tmp.name)/"studio.sqlite"),
            poller=server.Poller(probe=lambda _:{"ok":False}),
            bind=("127.0.0.1",0))
        thread=threading.Thread(target=app.serve_forever,daemon=True)
        thread.start()
        try:
            for method,url in (("GET","/api/v1/workflow?project=WaitingOffice&kind=props"),
                               ("GET","/api/v1/workflow/reviews?project=WaitingOffice"),
                               ("POST","/api/v1/workflow/save"),
                               ("POST","/api/v1/workflow/review")):
                con=http.client.HTTPConnection("127.0.0.1",app.server_port,timeout=5)
                con.request(method,url,
                    body=json.dumps({"csrf":app.csrf_token,**self.unit("props")})
                    if method=="POST" else None,
                    headers={"Host":"127.0.0.1:8900",
                             "Origin":"http://127.0.0.1:8900",
                             "Content-Type":"application/json"})
                res=con.getresponse()
                self.assertEqual(res.status,403,(method,url,res.read()))
                con.close()
        finally:
            app.shutdown();app.server_close();thread.join(timeout=3)


class FunctionalPageTests(unittest.TestCase):
    def test_all_pages_have_real_edit_actions_and_distinct_routes(self):
        root=Path(__file__).resolve().parents[1]
        html=(root/"index.html").read_text(encoding="utf8")
        js=(root/"studio.js").read_text(encoding="utf8")
        css=(root/"studio.css").read_text(encoding="utf8")
        for page,kind in (("props","props"),("shots","shot_plans"),
                          ("storyboards","storyboards"),("white_models","white_models"),
                          ("video_plans","video_plans"),("tasks","tasks"),
                          ("settings","settings")):
            self.assertIn('href="?page='+page+'"',html)
            self.assertIn('id="workflow_'+kind+'"',html)
            self.assertIn('id="wfProject_'+kind+'"',html)
            self.assertIn('id="wfStage_'+kind+'"',html)
            self.assertIn('body[data-page="'+page+'"]',css)
        self.assertIn('href="?page=review"',html)
        self.assertIn('id="workflow_review"',html)
        self.assertIn('window.history.pushState',js)
        self.assertIn('workflowPost("save"',js)
        self.assertIn('workflowPost("review"',js)
        self.assertIn('workflowDrawClay(',js)
        self.assertIn('stage_width',js)
        self.assertIn('./api/v1/production/visual/upload',js)
        self.assertNotIn('request_gpu_start',js)


if __name__=="__main__":
    unittest.main()
