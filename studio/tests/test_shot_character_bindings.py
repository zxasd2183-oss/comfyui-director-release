"""Per-shot role binding invariants: immutable snapshots, scope and planning gates."""
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
import character_library as v1
import character_library_v2 as v2
import shot_character_bindings as binds
import production_core as prod
import studio_server as studio
import visual_library as visuals

PNG=bytes.fromhex(
 "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
 "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")


class ShotBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=str(Path(self.tmp.name)/"production.sqlite")
        with closing(prod.open_db(self.db)) as db:
            visuals.prepare_schema(db);v1.prepare_schema(db)
            v2.prepare_schema(db);binds.prepare_schema(db)
            prod.create_project(db,"WaitingOffice","待回答事务所")
            prod.create_project(db,"OtherProject","其他工程")
            for p in ("WaitingOffice","OtherProject"):
                prod.create_episode(db,p,"EP01","首集",1)
                for num in range(1,4):
                    prod.create_shot(db,p,f"EP01",f"{num:02d}",num,4000)
        for p in ("WaitingOffice","OtherProject"):
            v1.create_character(self.db,{
                "project_id":p,"character_id":"CHAR_GPT",
                "display_name":"吉皮提","role":"main","brand_basis":"Abstract",
                "design_language":"Chestnut short hair and amber eyes",
                "character_notes":"Coordinator",
            },"owner")
        v1.create_character(self.db,{
            "project_id":"WaitingOffice","character_id":"CHAR_ZERO",
            "display_name":"零","role":"main","brand_basis":"Original",
            "design_language":"Right wrist red string","character_notes":"Mystery",
        },"owner")

    def binding(self,shot="01",**kwargs):
        return {"project_id":"WaitingOffice","episode_id":"EP01","shot_id":shot,
                "character_id":"CHAR_GPT","expected_revision":0,
                "view_direction":"front","screen_side":"center",
                "outfit_id":"GPT_DAILY_01","hair_variant_id":"GPT_HAIR_01",
                "expression":"思考","pose":"站姿",
                "prop_state_before":"右手持记录板",
                "prop_state_after":"右手持记录板",
                "note":"未批准角色包；仅供分镜规划","asset_ids":[],
                **kwargs}

    def save(self,shot="01",**kwargs):
        return binds.bind_character(self.db,self.binding(shot,**kwargs),"owner")

    def add_v2(self,category="rules"):
        ref=None
        if category in ("master","face","turnaround"):
            ref=visuals.upload_visual(self.db,{
                "project_id":"WaitingOffice","episode_id":"EP01",
                "kind":"character","subject_id":"CHAR_GPT",
                "filename":"reference.png",
                "image_base64":base64.b64encode(PNG).decode()
            },"owner")["visual_id"]
        details={"severity":"hard","forbidden_change":"No logo"} if category=="rules" else {"framing":"full_body"}
        data={"project_id":"WaitingOffice","character_id":"CHAR_GPT",
              "category":category,"subtype":"identity","label":"测试资产",
              "note":"人工校验的原创角色资产","details":details,
              "source_visual_id":ref}
        item=v2.create_asset(self.db,data,"owner")["item_id"]
        for action in ("submit","approve"):
            v2.review_asset(self.db,{"project_id":"WaitingOffice","character_id":"CHAR_GPT",
                "item_id":item,"expected_revision":1,"decision":action,
                "rationale":"已确认没有官方 Logo 且角色特征稳定"},"owner")
        return item

    def test_binding_is_planning_only_with_no_approved_assets(self):
        result=self.save()
        self.assertFalse(result["gpu_action"])
        self.assertEqual(result["binding_status"],"planning_only")
        out=binds.list_bindings(self.db,"WaitingOffice","EP01")
        self.assertEqual(out["binding_count"],1)
        self.assertFalse(out["can_generate_final"])
        one=out["bindings"][0]
        self.assertFalse(one["production_ready"])
        self.assertEqual(one["profile_revision"],1)
        self.assertEqual(one["asset_refs"],[])
        self.assertEqual(one["profile_snapshot"]["design_language"],
                         "Chestnut short hair and amber eyes")
        with closing(prod.open_db(self.db,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM production_shots "
                                        "WHERE project_id='WaitingOffice'").fetchone()[0],3)
            self.assertEqual(db.execute("SELECT SUM(duration_ms) FROM production_shots "
                                        "WHERE project_id='WaitingOffice'").fetchone()[0],12000)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM character_master_events").fetchone()[0],0)
            self.assertTrue(prod.verify_chain(db))

    def test_snapshot_survives_profile_revisions_and_binding_updates(self):
        item=self.add_v2("rules")
        self.save(asset_ids=[item])
        data=binds.list_bindings(self.db,"WaitingOffice","EP01")["bindings"][0]
        first_hash=data["asset_refs"][0]["approval_hash"]
        original=data["profile_snapshot"]["design_language"]
        v1.update_character(self.db,{"project_id":"WaitingOffice",
             "character_id":"CHAR_GPT","expected_revision":1,
             "display_name":"吉皮提","role":"main","brand_basis":"Abstract",
             "design_language":"New hair design NOT in locked shot",
             "character_notes":"Coordinator"},"owner")
        after=binds.list_bindings(self.db,"WaitingOffice","EP01")["bindings"][0]
        self.assertEqual(after["profile_revision"],1)
        self.assertEqual(after["profile_snapshot"]["design_language"],original)
        self.assertEqual(after["asset_refs"][0]["approval_hash"],first_hash)
        changed=self.save(expected_revision=1,expression="微笑",asset_ids=[item])
        self.assertEqual(changed["revision"],2)
        after=binds.list_bindings(self.db,"WaitingOffice","EP01")["bindings"][0]
        self.assertEqual(after["profile_revision"],2)
        self.assertEqual(after["expression"],"微笑")
        with closing(prod.open_db(self.db,initialize=False)) as db:
            history=db.execute("SELECT snapshot_json FROM shot_character_binding_history_v2 "
                "ORDER BY binding_revision").fetchall()
            self.assertEqual(len(history),2)
            self.assertEqual(json.loads(history[0][0])["expression"],"思考")
            self.assertEqual(json.loads(history[1][0])["expression"],"微笑")
            self.assertTrue(prod.verify_chain(db))

    def test_cannot_bind_unreviewed_assets(self):
        item=v2.create_asset(self.db,{
            "project_id":"WaitingOffice","character_id":"CHAR_GPT",
            "category":"rules","subtype":"rule","label":"候选",
            "note":"尚未审核","details":{"severity":"hard"},
            "source_visual_id":None},"owner")["item_id"]
        with self.assertRaises(v1.CharacterError) as ctx:
            self.save(asset_ids=[item])
        self.assertEqual(ctx.exception.reason,"shot_asset_not_approved")
        self.assertEqual(binds.list_bindings(self.db,"WaitingOffice","EP01")["binding_count"],0)

    def test_adjacent_continuity_conflict_and_gap_not_inferred(self):
        self.save("01",prop_state_after="右手拿资料板")
        self.save("02",prop_state_before="空手",outfit_id="NEW_COSTUME")
        self.save("03",hair_variant_id="OTHER_HAIR",prop_state_before="空手")
        data=binds.list_bindings(self.db,"WaitingOffice","EP01")
        types=[x["rule"] for x in data["findings"]]
        self.assertIn("costume_changed",types)
        self.assertIn("hair_variant_changed",types)
        self.assertIn("prop_state_mismatch",types)
        self.assertTrue(all(x["severity"]=="review" for x in data["findings"]))

    def test_cross_project_shot_and_asset_scope_rejection(self):
        with self.assertRaises(v1.CharacterError) as ctx:
            self.save(project_id="OtherProject",shot="01",character_id="CHAR_ZERO")
        self.assertEqual(ctx.exception.reason,"character_not_found")
        with self.assertRaises(v1.CharacterError):
            self.save(shot="99")
        with self.assertRaises(v1.CharacterError):
            self.save(episode_id="EP02")

    def test_stale_version_rejected_and_original_unchanged(self):
        self.save()
        with self.assertRaises(v1.CharacterError) as ctx:
            self.save(note="stale edit",expected_revision=0)
        self.assertEqual(ctx.exception.reason,"stale_shot_binding_revision")
        current=binds.list_bindings(self.db,"WaitingOffice","EP01")["bindings"][0]
        self.assertEqual(current["binding_revision"],1)
        with self.assertRaises(v1.CharacterError):
            self.save(screen_side="invalid",expected_revision=1)
        with closing(prod.open_db(self.db,initialize=False)) as db:
            self.assertTrue(prod.verify_chain(db))

    def test_anonymous_http_denied_and_nonexistent_content_not_public(self):
        app=studio.StudioServer(str(Path(self.tmp.name)/"studio.sqlite"),
            poller=studio.Poller(probe=lambda _:{"ok":False}),bind=("127.0.0.1",0))
        t=threading.Thread(target=app.serve_forever,daemon=True)
        t.start()
        try:
            conn=http.client.HTTPConnection("127.0.0.1",app.server_port,timeout=5)
            conn.request("GET","/api/v1/characters/shot-bindings?project=WaitingOffice&episode=EP01",
                         headers={"Host":"127.0.0.1:8900"})
            res=conn.getresponse()
            self.assertEqual(res.status,403)
            conn.close()
            conn=http.client.HTTPConnection("127.0.0.1",app.server_port,timeout=5)
            conn.request("POST","/api/v1/characters/shot-bindings/save",
                         body=json.dumps({"csrf":app.csrf_token,**self.binding()}),
                         headers={"Host":"127.0.0.1:8900",
                                  "Origin":"http://127.0.0.1:8900",
                                  "Content-Type":"application/json"})
            res=conn.getresponse()
            self.assertEqual(res.status,403)
            conn.close()
        finally:
            app.shutdown();app.server_close();t.join(timeout=3)


if __name__=="__main__":
    unittest.main()
