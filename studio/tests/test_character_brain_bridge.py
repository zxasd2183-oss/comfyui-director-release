"""End-to-end project character brain bridge, scoped to Studio; no GPU."""
import base64
import json
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"vps-control"))
import studio_brain as brain
import production_core as prod
import visual_library as media
import hub_rpc

PNG=bytes.fromhex(
  "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
  "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")


class CharacterBrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/"production.sqlite")
        with closing(prod.open_db(self.path)) as db:
            media.prepare_schema(db)
            import character_library as character
            character.prepare_schema(db)
            prod.create_project(db,"WaitingOffice","待回答事务所")
            prod.create_project(db,"OtherProject","隔离工程")
            prod.create_episode(db,"WaitingOffice","EP01","第一集",1)
            prod.create_episode(db,"WaitingOffice","EP02","第二集",2)
            prod.create_episode(db,"OtherProject","EP01","其他分集",1)
            prod.create_shot(db,"WaitingOffice","EP01","01",1,3000)

    def profile(self):
        return {"project_id":"WaitingOffice","character_id":"CHAR_GPT",
                "display_name":"吉皮提","role":"main",
                "brand_basis":"Original abstract interlacing; never official logo",
                "design_language":"Ivory teal garment with subtle junction motifs",
                "character_notes":"Gentle coordinator; original independent anime character"}

    def execute(self,tool,params):
        payload=hub_rpc.check_args(tool,params)
        return brain.execute(self.path,tool,payload)

    def add_visual(self,subject,episode="EP01",project="WaitingOffice"):
        return media.upload_visual(self.path,{"project_id":project,
            "episode_id":episode,"kind":"character","subject_id":subject,
            "filename":"candidate.png","image_base64":base64.b64encode(PNG).decode()},
            actor="test_operator")["visual_id"]

    def test_create_and_list_cross_episode_candidates_without_mutation(self):
        one=self.add_visual("CHAR_GPT")
        two=self.add_visual("CHAR_GPT",episode="EP02")
        response=self.execute("create_project_character",self.profile())
        self.assertTrue(response["ok"])
        self.assertFalse(response["gpu_action"])
        data=self.execute("get_project_characters",{"project_id":"WaitingOffice"})
        self.assertEqual({v["visual_id"] for v in data["characters"][0]["visuals"]},
                         {one,two})
        self.assertIsNone(data["characters"][0]["master"])
        self.assertIn("no_official_logo",data["logo_policy"])
        with closing(prod.open_db(self.path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM visual_media").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM production_shots").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM character_master_events").fetchone()[0],0)
            self.assertTrue(prod.verify_chain(db))

    def test_link_composite_and_versioned_edit_but_no_approval_tool(self):
        visual_id=self.add_visual("CHAR_GROUP")
        self.execute("create_project_character",self.profile())
        link={"project_id":"WaitingOffice","character_id":"CHAR_GPT",
              "visual_id":visual_id,"reference_type":"inspiration"}
        self.assertFalse(self.execute("link_project_character_visual",link)["already_linked"])
        self.assertTrue(self.execute("link_project_character_visual",link)["already_linked"])
        updated={**self.profile(),"expected_revision":1,
                 "display_name":"吉皮提 · 新版"}
        self.assertEqual(self.execute("update_project_character",updated)["revision"],2)
        with self.assertRaises(brain.BrainError) as ctx:
            self.execute("update_project_character",updated)
        self.assertEqual(ctx.exception.reason,"stale_character_revision")
        entry=self.execute("get_project_characters",
                          {"project_id":"WaitingOffice"})["characters"][0]
        self.assertEqual(entry["display_name"],"吉皮提 · 新版")
        self.assertEqual(entry["visuals"][0]["reference_type"],"inspiration")
        self.assertIsNone(entry["master"])
        for forbidden in ("approve_character_master","request_gpu_start",
                          "delete_character_profile","import_random_url"):
            self.assertNotIn(forbidden,brain.ALL_TOOLS)

    def test_cross_project_visuals_must_never_be_linked(self):
        self.execute("create_project_character",self.profile())
        foreign=self.add_visual("CHAR_GPT",project="OtherProject")
        link={"project_id":"WaitingOffice","character_id":"CHAR_GPT",
              "visual_id":foreign,"reference_type":"inspiration"}
        with self.assertRaises(brain.BrainError) as ctx:
            self.execute("link_project_character_visual",link)
        self.assertEqual(ctx.exception.status,404)
        with closing(prod.open_db(self.path,initialize=False)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM character_visual_links").fetchone()[0],0)

    def test_bounded_arguments_and_no_unsafe_fields(self):
        for tool,args in [
            ("create_project_character",{**self.profile(),"gpu_start":True}),
            ("create_project_character",{**self.profile(),"role":"untrusted"}),
            ("create_project_character",{**self.profile(),"character_notes":"x"*1201}),
            ("create_project_character",{**self.profile(),"character_id":"../../etc"}),
            ("update_project_character",{**self.profile(),"expected_revision":True}),
            ("link_project_character_visual",{"project_id":"WaitingOffice",
               "character_id":"CHAR_GPT","visual_id":"VIS_12345",
               "reference_type":"official_logo"}),
        ]:
            with self.subTest(tool=tool):
                with self.assertRaises(hub_rpc.HubError):
                    hub_rpc.check_args(tool,args)
        self.assertEqual(len(brain.ALL_TOOLS),13)
        self.assertEqual(len(hub_rpc.BRAIN_TOOLS),10)
        self.assertTrue(hub_rpc.BRAIN_TOOLS.issubset(brain.ALL_TOOLS))
        # Three new literal-argument endpoints use the existing HMAC
        # brain link directly, without changing legacy Hub route dispatch.
        self.assertTrue({"get_production_scenes",
                         "get_production_episode_readiness",
                         "create_production_scene"}.issubset(brain.ALL_TOOLS))
        self.assertTrue(brain.ALL_TOOLS.isdisjoint({"approve_character_master"}))

    def test_broken_audit_blocks_brain_catalog_writes(self):
        with closing(prod.open_db(self.path)) as db:
            db.execute("UPDATE audit_chain SET detail='tampered' WHERE id=1")
        with self.assertRaises(brain.BrainError) as ctx:
            self.execute("create_project_character",self.profile())
        self.assertEqual(ctx.exception.reason,"audit_integrity_failure")


if __name__=="__main__":
    unittest.main()
