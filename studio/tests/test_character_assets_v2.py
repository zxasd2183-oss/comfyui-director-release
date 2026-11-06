"""V2 role asset categories, immutable history, review gate and EP01 preservation."""
import base64
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import character_library as v1
import character_library_v2 as v2
import production_core as prod
import visual_library as visual
import studio_server as server

PNG=bytes.fromhex(
 "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
 "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")


class V2AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/"production.sqlite")
        with closing(prod.open_db(self.path)) as db:
            visual.prepare_schema(db)
            v1.prepare_schema(db)
            v2.prepare_schema(db)
            prod.create_project(db,"WaitingOffice","待回答事务所")
            prod.create_project(db,"OtherProject","other")
            prod.create_episode(db,"WaitingOffice","EP01","Pilot",1)
            prod.create_episode(db,"OtherProject","EP01","Other",1)
            prod.create_shot(db,"WaitingOffice","EP01","01",1,3000)
        v1.create_character(self.path,{
            "project_id":"WaitingOffice","character_id":"CHAR_GPT",
            "display_name":"吉皮提","role":"main",
            "brand_basis":"Abstract connections; no logo",
            "design_language":"Short chestnut hair; amber eyes",
            "character_notes":"EP01 organizer",
        },"tester")
        v1.create_character(self.path,{
            "project_id":"OtherProject","character_id":"CHAR_GPT",
            "display_name":"Other","role":"main",
            "brand_basis":"","design_language":"","character_notes":"",
        },"tester")

    def item(self,category="profile",**other):
        data={"project_id":"WaitingOffice","character_id":"CHAR_GPT",
              "category":category,"subtype":"identity","label":"角色锁定",
              "note":"候选设计，不含官方标志",
              "details":{"identity_lock":"深栗色齐颈短发与琥珀色眼睛"},
              "source_visual_id":None}
        if category!="profile":
            key=v2.CATEGORY_FIELDS[category][0]
            data["details"]={key:
                "front" if category=="turnaround" else
                "hard" if category=="rules" else
                "HAIR_ID"}
        data.update(other)
        return data

    def create(self,category="profile",**kw):
        return v2.create_asset(self.path,self.item(category,**kw),"owner")

    def visual(self,subject="CHAR_GPT",project="WaitingOffice"):
        return visual.upload_visual(self.path,{
            "project_id":project,"episode_id":"EP01","kind":"character",
            "subject_id":subject,"filename":"source.png",
            "image_base64":base64.b64encode(PNG).decode()
        },actor="owner")["visual_id"]

    def review(self,item_id,decision,reason="人工审核已确认人设一致性和无官方标志"):
        return v2.review_asset(self.path,{
            "project_id":"WaitingOffice","character_id":"CHAR_GPT",
            "item_id":item_id,"expected_revision":1,
            "decision":decision,"rationale":reason,
        },actor="verified_owner")

    def test_twelve_categories_are_independent_drafts_and_episode_unmodified(self):
        self.assertEqual(len(v2.CATEGORIES),12)
        ids=set()
        for category in v2.CATEGORIES:
            record=self.create(category)
            self.assertEqual(record["status"],"draft")
            ids.add(record["item_id"])
        self.assertEqual(len(ids),12)
        catalog=v2.list_assets(self.path,"WaitingOffice","CHAR_GPT")
        self.assertEqual({a["category"] for a in catalog["assets"]},set(v2.CATEGORIES))
        self.assertTrue(all(x["approved"]==0 for x in catalog["counts"].values()))
        self.assertEqual(catalog["pack_status"],"not_approved")
        with closing(prod.open_db(self.path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM production_shots").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM character_master_events").fetchone()[0],0)
            self.assertTrue(prod.verify_chain(db))

    def test_draft_revision_history_and_stale_lock(self):
        one=self.create()
        previous=self.item()
        edited={**previous,"item_id":one["item_id"],"expected_revision":1,
                "label":"角色锁定 V2"}
        result=v2.revise_asset(self.path,edited,"owner")
        self.assertEqual(result["revision"],2)
        with self.assertRaises(v1.CharacterError) as caught:
            v2.revise_asset(self.path,edited,"owner")
        self.assertEqual(caught.exception.reason,"stale_v2_asset_revision")
        with closing(prod.open_db(self.path,initialize=False)) as db:
            rows=db.execute("SELECT snapshot_json FROM character_assets_v2_history "
                            "WHERE item_id=? ORDER BY revision",
                            (one["item_id"],)).fetchall()
            self.assertEqual(len(rows),2)
            self.assertEqual(json.loads(rows[0][0])["label"],"角色锁定")
            self.assertEqual(json.loads(rows[1][0])["label"],"角色锁定 V2")
            self.assertTrue(prod.verify_chain(db))

    def test_review_is_explicit_ordered_and_unapproved_pack_remains_locked(self):
        record=self.create("rules")
        item_id=record["item_id"]
        with self.assertRaises(v1.CharacterError) as err:
            self.review(item_id,"approve")
        self.assertEqual(err.exception.reason,"invalid_v2_review_transition")
        self.assertEqual(self.review(item_id,"submit")["status"],"in_review")
        self.assertEqual(self.review(item_id,"approve")["status"],"approved")
        with self.assertRaises(v1.CharacterError) as err:
            v2.revise_asset(self.path,{**self.item("rules"),
                "item_id":item_id,"expected_revision":1},"owner")
        self.assertEqual(err.exception.reason,"v2_asset_frozen")
        response=v2.list_assets(self.path,"WaitingOffice","CHAR_GPT")
        self.assertEqual(response["assets"][0]["status"],"approved")
        self.assertEqual(len(response["assets"][0]["reviews"]),2)
        self.assertEqual(response["pack_status"],"not_approved")
        with closing(prod.open_db(self.path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM character_master_events").fetchone()[0],0)
            self.assertTrue(prod.verify_chain(db))

    def test_image_assets_cannot_approve_without_source_or_with_group_guide(self):
        item=self.create("master")
        self.review(item["item_id"],"submit")
        with self.assertRaises(v1.CharacterError) as err:
            self.review(item["item_id"],"approve")
        self.assertEqual(err.exception.reason,"v2_visual_required_for_approval")
        guide=self.visual("CHAR_GROUP")
        v1.link_visual(self.path,{"project_id":"WaitingOffice",
            "character_id":"CHAR_GPT","visual_id":guide,
            "reference_type":"inspiration"},"owner")
        item=self.create("master",source_visual_id=guide)
        self.review(item["item_id"],"submit")
        with self.assertRaises(v1.CharacterError) as err:
            self.review(item["item_id"],"approve")
        self.assertEqual(err.exception.reason,"v2_individual_visual_required")

    def test_original_individual_image_explicitly_approved_but_not_pack(self):
        ref=self.visual()
        entry=self.create("master",source_visual_id=ref)
        self.review(entry["item_id"],"submit")
        out=self.review(entry["item_id"],"approve")
        self.assertEqual(out["status"],"approved")
        data=v2.list_assets(self.path,"WaitingOffice","CHAR_GPT")
        self.assertEqual(data["assets"][0]["source_sha256"],
                         data["assets"][0]["source_sha256"].lower())
        self.assertEqual(data["counts"]["master"]["approved"],1)
        self.assertEqual(data["pack_status"],"not_approved")
        with closing(prod.open_db(self.path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],1)
            self.assertTrue(prod.verify_chain(db))

    def test_foreign_source_rejected_even_for_identical_character_id(self):
        foreign=self.visual(project="OtherProject")
        with self.assertRaises(v1.CharacterError) as err:
            self.create("face",source_visual_id=foreign)
        self.assertEqual(err.exception.reason,"character_visual_not_found")

    def test_wrong_fields_invalid_color_and_logo_rule_enums(self):
        for category,payload in [
            ("turnaround",{"details":{"direction":"southeast"}}),
            ("rules",{"details":{"severity":"unreviewed"}}),
            ("palette",{"details":{"scope":"hair","hex_srgb":"not-a-hex"}}),
            ("profile",{"source_visual_id":"invalid source"}),
            ("profile",{"details":{"unregistered_field":"bad"}}),
            ("profile",{"label":"x"*200}),
            ("profile",{"status":"approved"}),
        ]:
            with self.subTest(category=category,payload=payload):
                with self.assertRaises(v1.CharacterError):
                    self.create(category,**payload)

    def test_unauthorized_http_v2_paths_blocked(self):
        svc=server.StudioServer(str(Path(self.temp.name)/"studio.sqlite"),
            poller=server.Poller(probe=lambda _:{"ok":False,"reason":"off"}),
            bind=("127.0.0.1",0))
        import threading
        import http.client
        thread=threading.Thread(target=svc.serve_forever,daemon=True)
        thread.start()
        try:
            conn=http.client.HTTPConnection("127.0.0.1",svc.server_port,timeout=5)
            conn.request("GET","/api/v1/characters/assets?project=WaitingOffice&character=CHAR_GPT",
                         headers={"Host":"127.0.0.1:8900"})
            response=conn.getresponse()
            self.assertEqual(response.status,403,response.read())
            conn.close()
            conn=http.client.HTTPConnection("127.0.0.1",svc.server_port,timeout=5)
            conn.request("POST","/api/v1/characters/assets/create",
                         body=json.dumps({"csrf":svc.csrf_token}),
                         headers={"Host":"127.0.0.1:8900",
                                  "Origin":"http://127.0.0.1:8900",
                                  "Content-Type":"application/json"})
            response=conn.getresponse()
            self.assertEqual(response.status,403,response.read())
            conn.close()
        finally:
            svc.shutdown();svc.server_close();thread.join(timeout=3)

    def test_v2_frontend_has_no_official_logo_or_gpu_action(self):
        root=Path(__file__).resolve().parents[1]
        script=(root/"studio.js").read_text(encoding="utf8")
        self.assertIn("character-v2-tabs",script)
        self.assertIn("v2JipiteDefaults",script)
        self.assertIn("assets/review",script)
        self.assertIn("source_visual_id",script)
        self.assertNotIn("request_gpu_start",script)


if __name__=="__main__":
    unittest.main()
