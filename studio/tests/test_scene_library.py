"""Full-stack scene catalog: data, genuine reference uploads, owner review, routes."""
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
import production_core as prod
import visual_library as visuals
import scene_library as scenes
import studio_server as studio

PNG=bytes.fromhex(
 "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
 "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")


class SceneLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/"production.sqlite")
        with closing(prod.open_db(self.path)) as db:
            visuals.prepare_schema(db)
            scenes.prepare_schema(db)
            for pid in ("WaitingOffice","Unrelated"):
                prod.create_project(db,pid,pid)
                prod.create_episode(db,pid,"EP01","Episode 1",1)
                prod.create_shot(db,pid,"EP01","01",1,3000)

    def profile(self,scene_id="SCN_OFFICE",project_id="WaitingOffice",**more):
        return {"project_id":project_id,"scene_id":scene_id,
                "display_name":"事务所内景","scene_type":"interior",
                "layout_notes":"北墙有窗，南墙入口；书桌固定在东侧。",
                "lighting_notes":"白天窗光从北侧进入。",
                "camera_rules":"保持180度轴线，门始终在画面左侧。",
                "continuity_rules":"书架和门窗位置不得在镜头间改变。",
                "scene_notes":"可跨剧集复用。",
                **more}

    def create(self,**more):
        return scenes.create_scene(self.path,self.profile(**more),"owner")

    def upload(self,scene_id="SCN_OFFICE",project_id="WaitingOffice"):
        return visuals.upload_visual(self.path,{
            "project_id":project_id,"episode_id":"EP01","kind":"scene",
            "subject_id":scene_id,"filename":"office.png",
            "image_base64":base64.b64encode(PNG).decode("ascii")
        },"owner")["visual_id"]

    def review(self,decision,visual_id=None,revision=1,reason="人工确认房间布局和窗光方向一致。"):
        return scenes.review_scene(self.path,{
            "project_id":"WaitingOffice","scene_id":"SCN_OFFICE",
            "expected_revision":revision,"decision":decision,
            "visual_id":visual_id,"rationale":reason
        },"verified_owner")

    def test_create_list_and_legacy_shots_untouched(self):
        x=self.create()
        self.assertEqual(x["status"],"draft")
        self.assertFalse(x["gpu_action"])
        result=scenes.list_scenes(self.path,"WaitingOffice")
        self.assertEqual(len(result["scenes"]),1)
        self.assertEqual(result["scenes"][0]["layout_notes"],
                         self.profile()["layout_notes"])
        self.assertEqual(result["scenes"][0]["revision"],1)
        self.assertIsNone(result["scenes"][0]["canonical"])
        self.assertEqual(result["available_visuals"],[])
        with closing(prod.open_db(self.path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT SUM(duration_ms) FROM production_shots "
                "WHERE project_id='WaitingOffice'").fetchone()[0],3000)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],0)
            self.assertTrue(prod.verify_chain(db))

    def test_review_requires_linked_scene_specific_image(self):
        self.create()
        self.assertEqual(self.review("submit")["status"],"in_review")
        with self.assertRaises(scenes.SceneError) as ctx:
            self.review("approve")
        self.assertEqual(ctx.exception.reason,"scene_approved_visual_required")
        own=self.upload()
        with self.assertRaises(scenes.SceneError) as ctx:
            self.review("approve",own)
        self.assertEqual(ctx.exception.reason,"scene_approved_visual_not_linked")
        scenes.link_scene_visual(self.path,{"project_id":"WaitingOffice",
            "scene_id":"SCN_OFFICE","visual_id":own,"reference_type":"overview"},"owner")
        self.assertEqual(self.review("approve",own)["status"],"approved")
        result=scenes.list_scenes(self.path,"WaitingOffice")["scenes"][0]
        self.assertEqual(result["approved_revision"],1)
        self.assertEqual(result["canonical"]["visual_id"],own)
        self.assertEqual(result["canonical"]["visual_sha256"],result["visuals"][0]["sha256"])
        with closing(prod.open_db(self.path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],1)
            self.assertTrue(prod.verify_chain(db))

    def test_versions_preserve_last_approved_snapshot(self):
        self.create()
        own=self.upload()
        scenes.link_scene_visual(self.path,{"project_id":"WaitingOffice",
            "scene_id":"SCN_OFFICE","visual_id":own,"reference_type":"overview"},"owner")
        self.review("submit")
        self.review("approve",own)
        update=self.profile(layout_notes="改版：西侧新增门。")
        update["expected_revision"]=1
        revised=scenes.update_scene(self.path,update,"owner")
        self.assertEqual(revised["revision"],2)
        self.assertEqual(revised["status"],"draft")
        history=scenes.list_scenes(self.path,"WaitingOffice")["scenes"][0]
        self.assertEqual(history["approved_revision"],1)
        self.assertEqual(history["canonical"]["visual_id"],own)
        with closing(prod.open_db(self.path,initialize=False)) as db:
            snapshots=db.execute("SELECT snapshot_json FROM scene_profile_history "
                "ORDER BY revision").fetchall()
            self.assertEqual(len(snapshots),2)
            self.assertEqual(json.loads(snapshots[0][0])["layout_notes"],
                             self.profile()["layout_notes"])
            self.assertEqual(json.loads(snapshots[1][0])["layout_notes"],
                             "改版：西侧新增门。")
            self.assertTrue(prod.verify_chain(db))

    def test_cross_project_scene_reference_and_group_image_never_approved(self):
        self.create()
        foreign=self.upload(project_id="Unrelated")
        with self.assertRaises(scenes.SceneError) as ctx:
            scenes.link_scene_visual(self.path,{
                "project_id":"WaitingOffice","scene_id":"SCN_OFFICE",
                "visual_id":foreign,"reference_type":"overview"},"owner")
        self.assertEqual(ctx.exception.status,404)
        composite=self.upload("SCN_GROUP")
        scenes.link_scene_visual(self.path,{
            "project_id":"WaitingOffice","scene_id":"SCN_OFFICE",
            "visual_id":composite,"reference_type":"inspiration"},"owner")
        self.review("submit")
        with self.assertRaises(scenes.SceneError) as ctx:
            self.review("approve",composite)
        self.assertEqual(ctx.exception.reason,"scene_individual_visual_required")

    def test_reject_and_revision_conflicts_and_audit_chain(self):
        self.create()
        with self.assertRaises(scenes.SceneError):
            self.review("approve")
        self.review("submit")
        self.assertEqual(self.review("reject")["status"],"rejected")
        stale={**self.profile(),"expected_revision":2}
        with self.assertRaises(scenes.SceneError) as ctx:
            scenes.update_scene(self.path,stale,"owner")
        self.assertEqual(ctx.exception.reason,"stale_scene_revision")
        changed={**self.profile(),"expected_revision":1,"display_name":"事务所内景第二稿"}
        self.assertEqual(scenes.update_scene(self.path,changed,"owner")["revision"],2)
        with closing(prod.open_db(self.path,initialize=False)) as db:
            self.assertTrue(prod.verify_chain(db))

    def test_bad_fields_are_rejected(self):
        for data in [
            self.profile(scene_type="planetary"),
            self.profile(scene_id="../escape"),
            self.profile(layout_notes=""),
            self.profile(camera_rules="x"*1400),
            {**self.profile(),"status":"approved"},
        ]:
            with self.subTest(case=data):
                with self.assertRaises(scenes.SceneError):
                    scenes.create_scene(self.path,data,"owner")
        self.create()
        for payload in [
            {"project_id":"WaitingOffice","scene_id":"SCN_OFFICE",
             "visual_id":"VIS_notfound","reference_type":"overview"},
            {"project_id":"WaitingOffice","scene_id":"SCN_OFFICE",
             "visual_id":"VIS_notfound","reference_type":"official_logo"},
        ]:
            with self.assertRaises(scenes.SceneError):
                scenes.link_scene_visual(self.path,payload,"owner")

    def test_fails_closed_on_corrupt_audit(self):
        self.create()
        with closing(prod.open_db(self.path)) as db:
            db.execute("UPDATE audit_chain SET detail='tampered' WHERE id=1")
        with self.assertRaises(ValueError) as ctx:
            self.create(scene_id="SCN_OTHER")
        self.assertIn("audit_integrity_failure",str(ctx.exception))
        with closing(prod.open_db(self.path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM scene_profiles").fetchone()[0],1)

    def test_anonymous_http_scene_api_forbidden(self):
        server=studio.StudioServer(str(Path(self.temp.name)/"studio.sqlite"),
            poller=studio.Poller(probe=lambda _:{"ok":False}),bind=("127.0.0.1",0))
        worker=threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        try:
            for method,path,body in [
                ("GET","/api/v1/scenes?project=WaitingOffice",None),
                ("POST","/api/v1/scenes/create",json.dumps({
                    "csrf":server.csrf_token,**self.profile()})),
            ]:
                con=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
                con.request(method,path,body=body,headers={
                    "Host":"127.0.0.1:8900",
                    "Origin":"http://127.0.0.1:8900",
                    "Content-Type":"application/json"})
                response=con.getresponse()
                self.assertEqual(response.status,403,(method,response.read()))
                con.close()
            # Same document path, but distinct client-side page navigation.
            con=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
            con.request("GET","/?page=scenes",headers={"Host":"127.0.0.1:8900"})
            response=con.getresponse()
            self.assertEqual(response.status,200,response.read()[:200])
            con.close()
        finally:
            server.shutdown();server.server_close();worker.join(timeout=4)

    def test_scene_page_is_real_form_not_scroll_anchor(self):
        root=Path(__file__).resolve().parents[1]
        html=(root/"index.html").read_text(encoding="utf8")
        js=(root/"studio.js").read_text(encoding="utf8")
        css=(root/"studio.css").read_text(encoding="utf8")
        for path in ("?page=home","?page=projects","?page=characters",
                     "?page=scenes","?page=shots"):
            self.assertIn(path,html)
        self.assertNotIn('href="#characters"',html)
        self.assertIn('id="sceneEditor"',html)
        self.assertIn('id="sceneUploadForm"',html) if 'id="sceneUploadForm"' in html else self.assertIn('scene-upload-form',js)
        self.assertIn('"/api/v1/scenes/create"',(root/"studio_server.py").read_text())
        self.assertIn('scenePost("review"',js)
        self.assertIn('window.history.pushState',js)
        self.assertIn('popstate',js)
        self.assertIn('body[data-page="scenes"]',css)
        self.assertNotIn('request_gpu_start',js)


if __name__=="__main__":
    unittest.main()
