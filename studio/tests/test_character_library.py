"""Project-scoped character catalog, legacy image links, audit & no-GPU tests."""
import base64
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import production_core as prod
import character_library as catalog
import visual_library as visual
import studio_server as studio

PNG=bytes.fromhex(
 "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
 "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")


class CharacterLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/"production.sqlite")
        with closing(prod.open_db(self.path)) as db:
            visual.prepare_schema(db)
            catalog.prepare_schema(db)
            prod.create_project(db,"WaitingOffice","待回答事务所")
            prod.create_project(db,"OtherProject","其他工程")
            prod.create_episode(db,"WaitingOffice","EP01","第一集",1)
            prod.create_episode(db,"WaitingOffice","EP02","第二集",2)
            prod.create_episode(db,"OtherProject","EP01","无关工程",1)
            prod.create_shot(db,"WaitingOffice","EP01","01",1,3000)
            db.execute("INSERT INTO episode_outlines("
                "project_id,episode_id,revision,outline_sha256,body,updated_at)"
                "VALUES(?,?,?,?,?,?)",("WaitingOffice","EP01",2,"0"*64,
                                      "31-shot production outline",1))

    def profile(self,cid="CHAR_GPT",**overrides):
        return {"project_id":"WaitingOffice","character_id":cid,
                "display_name":"吉皮提","role":"main",
                "brand_basis":"Abstract interwoven connection; no official logo",
                "design_language":"Chestnut hair, ivory-teal uniform",
                "character_notes":"Gentle organizer, EP01 plot role",
                **overrides}

    def add_visual(self,subject="CHAR_GPT",episode="EP01",project="WaitingOffice"):
        return visual.upload_visual(self.path,{
            "project_id":project,"episode_id":episode,"kind":"character",
            "subject_id":subject,"filename":"candidate.png",
            "image_base64":base64.b64encode(PNG).decode()},
            actor="test_operator")

    def test_create_and_auto_match_episode_candidates_without_moving(self):
        self.add_visual()
        self.add_visual(episode="EP02")
        catalog.create_character(self.path,self.profile(),actor="test_operator")
        response=catalog.list_characters(self.path,"WaitingOffice")
        self.assertEqual(response["logo_policy"],
                         "abstract_visual_language_only_no_official_logo")
        self.assertEqual(len(response["characters"]),1)
        c=response["characters"][0]
        self.assertEqual(len(c["visuals"]),2)
        self.assertEqual({v["episode_id"] for v in c["visuals"]},{"EP01","EP02"})
        self.assertTrue(all(v["auto_matched"] for v in c["visuals"]))
        self.assertIsNone(c["master"])
        with closing(prod.open_db(self.path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM production_shots").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT body,revision FROM episode_outlines"
                                        ).fetchone()["revision"],2)
            self.assertTrue(prod.verify_chain(db))

    def test_link_composite_image_without_copy_and_explicit_master_review(self):
        c=catalog.create_character(self.path,self.profile(),actor="test_operator")
        self.assertFalse(c["gpu_action"])
        visual_id=self.add_visual(subject="CHAR_GROUP")["visual_id"]
        with self.assertRaises(catalog.CharacterError) as caught:
            catalog.set_master(self.path,{
                "project_id":"WaitingOffice","character_id":"CHAR_GPT",
                "visual_id":visual_id,"rationale":"Reviewed visual continuity"},
                actor="test_operator")
        self.assertEqual(caught.exception.reason,"character_visual_not_linked")
        link={"project_id":"WaitingOffice","character_id":"CHAR_GPT",
              "visual_id":visual_id,"reference_type":"inspiration"}
        self.assertFalse(catalog.link_visual(self.path,link,actor="test_operator")["already_linked"])
        self.assertTrue(catalog.link_visual(self.path,link,actor="test_operator")["already_linked"])
        self.assertIsNone(catalog.list_characters(self.path,"WaitingOffice")["characters"][0]["master"])
        with self.assertRaises(catalog.CharacterError):
            catalog.set_master(self.path,{**{k:v for k,v in link.items() if k!="reference_type"},
                "rationale":"short"},actor="test_operator")
        result=catalog.set_master(self.path,{
            "project_id":"WaitingOffice","character_id":"CHAR_GPT",
            "visual_id":visual_id,"rationale":"Reviewed character design and consistency"},
            actor="test_operator")
        self.assertEqual(result["master_visual_id"],visual_id)
        self.assertFalse(result["gpu_action"])
        entry=catalog.list_characters(self.path,"WaitingOffice")["characters"][0]
        self.assertEqual(entry["master"]["visual_id"],visual_id)
        self.assertEqual(entry["visuals"][0]["reference_type"],"inspiration")
        with closing(prod.open_db(self.path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM character_visual_links").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM character_master_events").fetchone()[0],1)
            self.assertTrue(prod.verify_chain(db))

    def test_revision_conflict_preserves_prior_profile_and_audit(self):
        catalog.create_character(self.path,self.profile(),actor="test_operator")
        fields={**self.profile(display_name="新吉皮提"),"expected_revision":1}
        result=catalog.update_character(self.path,fields,actor="test_operator")
        self.assertEqual(result["revision"],2)
        with self.assertRaises(catalog.CharacterError) as caught:
            catalog.update_character(self.path,fields,actor="test_operator")
        self.assertEqual(caught.exception.reason,"stale_character_revision")
        entry=catalog.list_characters(self.path,"WaitingOffice")["characters"][0]
        self.assertEqual(entry["display_name"],"新吉皮提")
        self.assertEqual(entry["revision"],2)
        with closing(prod.open_db(self.path,initialize=False)) as db:
            self.assertTrue(prod.verify_chain(db))

    def test_project_isolation_and_refusal_to_approve_other_project_images(self):
        catalog.create_character(self.path,self.profile(),actor="test_operator")
        foreign=self.add_visual(project="OtherProject")["visual_id"]
        data={"project_id":"WaitingOffice","character_id":"CHAR_GPT",
              "visual_id":foreign,"reference_type":"character_card"}
        with self.assertRaises(catalog.CharacterError) as caught:
            catalog.link_visual(self.path,data,actor="test_operator")
        self.assertEqual(caught.exception.reason,"character_visual_not_found")
        with self.assertRaises(catalog.CharacterError):
            catalog.list_characters(self.path,"missing_project")

    def test_duplicate_profiles_and_invalid_categories_are_blocked(self):
        catalog.create_character(self.path,self.profile(),actor="test_operator")
        with self.assertRaises(catalog.CharacterError) as caught:
            catalog.create_character(self.path,self.profile(),actor="test_operator")
        self.assertEqual(caught.exception.reason,"character_already_exists")
        with self.assertRaises(catalog.CharacterError):
            catalog.create_character(self.path,self.profile(cid="BAD/ID"),
                                     actor="test_operator")
        with self.assertRaises(catalog.CharacterError):
            catalog.create_character(self.path,self.profile(cid="CHAR_NEW",role="invalid"),
                                     actor="test_operator")

    def test_broken_audit_chain_blocks_edits(self):
        catalog.create_character(self.path,self.profile(),actor="test_operator")
        with closing(prod.open_db(self.path)) as db:
            db.execute("UPDATE audit_chain SET detail='tampered' WHERE id=1")
        with self.assertRaises(catalog.CharacterError) as caught:
            catalog.create_character(self.path,self.profile(cid="CHAR_ZERO"),
                                     actor="test_operator")
        self.assertEqual(caught.exception.reason,"audit_integrity_failure")


class CharacterHTTPAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app=studio.StudioServer(str(Path(self.tmp.name)/"studio.sqlite"),
            poller=studio.Poller(probe=lambda _:{"ok":False,"reason":"offline"}),
            bind=("127.0.0.1",0))
        with closing(prod.open_db(self.app.production_db_path)) as db:
            prod.create_project(db,"WaitingOffice","待回答事务所")
        self.thread=threading.Thread(target=self.app.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.app.shutdown()
        self.app.server_close()
        self.thread.join(timeout=3)

    def call(self,method,path,body=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.app.server_port,timeout=5)
        raw=json.dumps(body).encode() if body else None
        headers={"Host":"127.0.0.1:8900","Origin":"http://127.0.0.1:8900"}
        if raw is not None:headers["Content-Type"]="application/json"
        conn.request(method,path,body=raw,headers=headers)
        resp=conn.getresponse()
        status,payload=resp.status,json.loads(resp.read())
        conn.close()
        return status,payload

    def test_unauthenticated_character_catalog_and_writes_are_forbidden(self):
        status,data=self.call("GET","/api/v1/characters?project=WaitingOffice")
        self.assertEqual(status,403,data)
        self.assertEqual(data["reason"],"microsoft_owner_required")
        status,data=self.call("POST","/api/v1/characters/create",
                              {"csrf":self.app.csrf_token,"project_id":"WaitingOffice"})
        self.assertEqual(status,403,data)
        self.assertEqual(data["reason"],"microsoft_owner_required")


if __name__=="__main__":
    unittest.main()
