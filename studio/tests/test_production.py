"""Offline V0.9 production foundation checks; no GPU or network dependencies."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import production_core as p
import production_manage as cli

HASH1="a"*64
HASH2="b"*64
HASH3="c"*64


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/"production.sqlite"
        self.db=p.open_db(self.path)
        self.addCleanup(self.db.close)

    def basic(self):
        p.create_project(self.db,"SHOW01","短剧测试项目")
        p.create_episode(self.db,"SHOW01","EP01","第一集",1)
        p.create_shot(self.db,"SHOW01","EP01","S01",1,5200)
        p.create_shot(self.db,"SHOW01","EP01","S02",2,4800)

    def test_project_episode_shot_hierarchy_and_empty_summary(self):
        empty=p.dashboard(self.db)
        self.assertEqual(empty["counts"]["projects"],0)
        self.assertEqual(empty["audio_asset_count"],0)
        self.assertTrue(empty["audit_chain_verified"])
        self.basic()
        result=p.dashboard(self.db)
        self.assertEqual(result["counts"]["projects"],1)
        self.assertEqual(result["counts"]["episodes"],1)
        self.assertEqual(result["counts"]["production_shots"],2)
        self.assertEqual(result["projects"][0]["title"],"短剧测试项目")
        self.assertTrue(result["controls"]["gpu_power"] is False)
        self.assertTrue(p.verify_chain(self.db))

    def test_asset_versions_require_hash_and_audio_rights(self):
        self.basic()
        with self.assertRaisesRegex(p.ProductionError,"audio_rights"):
            p.add_asset(self.db,"A01","SHOW01","character_voice","VOICE01",1,HASH1,"")
        with self.assertRaisesRegex(p.ProductionError,"invalid_sha256"):
            p.add_asset(self.db,"A01","SHOW01","character_voice","VOICE01",1,"bad","licensed")
        p.add_asset(self.db,"A01","SHOW01","character_voice","VOICE01",1,HASH1,
                    "owner_recorded_consent")
        p.add_asset(self.db,"A02","SHOW01","character_visual","CHAR01",1,HASH2,
                    "owner_generated")
        self.assertEqual(p.dashboard(self.db)["audio_asset_count"],1)
        self.assertEqual(p.dashboard(self.db)["asset_kinds"]["character_visual"],1)
        with self.assertRaisesRegex(p.ProductionError,"asset_version_must_increase"):
            p.add_asset(self.db,"A03","SHOW01","character_voice","VOICE01",1,HASH3,
                        "consent")
        self.assertTrue(p.verify_chain(self.db))

    def test_cross_project_asset_link_rejected(self):
        self.basic()
        p.create_project(self.db,"SHOW02","另一个项目")
        p.add_asset(self.db,"A01","SHOW02","costume","COAT01",1,HASH1,"owner")
        with self.assertRaisesRegex(p.ProductionError,"asset_not_in_project"):
            p.attach_asset(self.db,"SHOW01","EP01","S01","A01","wardrobe")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM shot_assets").fetchone()[0],0)
        p.add_asset(self.db,"A02","SHOW01","character_visual","CHAR01",1,HASH2,"owner")
        p.attach_asset(self.db,"SHOW01","EP01","S01","A02","face_reference")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM shot_assets").fetchone()[0],1)

    def make_exception(self):
        self.basic()
        p.add_asset(self.db,"A01","SHOW01","character_voice","VOICE01",1,HASH1,
                    "signed_voice_consent")
        p.create_finding(self.db,"F01","SHOW01","EP01","S01","voice.timbre",HASH2,
                         "尾声变为电子音")
        p.draft_exception(self.db,"X01","F01",3200,4200,
                          "electronic_filter","剧情揭示 AI 身份",HASH2,"A01")

    def test_time_scoped_artistic_exception_and_audit(self):
        self.make_exception()
        row=self.db.execute("SELECT * FROM exceptions WHERE exception_id='X01'").fetchone()
        self.assertEqual((row["start_ms"],row["end_ms"]),(3200,4200))
        self.assertEqual(row["status"],"draft")
        with self.assertRaisesRegex(p.ProductionError,"explicit_review"):
            p.decide_exception(self.db,"X01","approve",1,actor="owner_local",confirmation="")
        res=p.decide_exception(self.db,"X01","approve",1,actor="owner_local",
                               confirmation="I_HAVE_REVIEWED_EVIDENCE")
        self.assertEqual(res["revision"],2)
        self.assertFalse(res["gpu_action"])
        self.assertEqual(p.dashboard(self.db)["exception_status"],{"approved":1})
        with self.assertRaisesRegex(p.ProductionError,"stale_exception_revision"):
            p.decide_exception(self.db,"X01","approve",1,actor="owner_local",
                               confirmation="I_HAVE_REVIEWED_EVIDENCE")
        self.assertTrue(p.verify_chain(self.db))

    def test_new_voice_revision_invalidates_approved_exception(self):
        self.make_exception()
        p.decide_exception(self.db,"X01","approve",1,actor="owner_local",
                           confirmation="I_HAVE_REVIEWED_EVIDENCE")
        p.add_asset(self.db,"A02","SHOW01","character_voice","VOICE01",2,HASH3,
                    "signed_voice_consent")
        row=self.db.execute("SELECT status,revision FROM exceptions WHERE exception_id='X01'").fetchone()
        self.assertEqual(tuple(row),("stale",3))
        with self.assertRaisesRegex(p.ProductionError,"only_draft"):
            p.decide_exception(self.db,"X01","approve",3,actor="owner_local",
                               confirmation="I_HAVE_REVIEWED_EVIDENCE")

    def test_revoke_does_not_erase_approval_audit(self):
        self.make_exception()
        p.decide_exception(self.db,"X01","approve",1,actor="owner_local",
                           confirmation="I_HAVE_REVIEWED_EVIDENCE")
        out=p.decide_exception(self.db,"X01","revoke",2,actor="owner_local",
                               confirmation="I_HAVE_REVIEWED_EVIDENCE")
        self.assertEqual(out["status"],"revoked")
        history=[r[0] for r in self.db.execute("SELECT action FROM audit_chain ORDER BY id")]
        self.assertIn("exception.approved",history)
        self.assertIn("exception.revoked",history)
        self.assertTrue(p.verify_chain(self.db))

    def test_exception_must_match_actual_shot_duration_and_asset(self):
        self.basic()
        p.create_finding(self.db,"F01","SHOW01","EP01","S01","color.tone",HASH1,
                         "镜头色温变化")
        with self.assertRaisesRegex(p.ProductionError,"exception_outside_shot"):
            p.draft_exception(self.db,"X01","F01",4100,6000,"cold","意图",HASH2)
        with self.assertRaisesRegex(p.ProductionError,"invalid_exception_time_range"):
            p.draft_exception(self.db,"X01","F01",2100,1800,"cold","意图",HASH2)

    def test_audit_detects_tampering_and_chain_rollback(self):
        self.basic()
        self.assertTrue(p.verify_chain(self.db))
        self.db.execute("UPDATE audit_chain SET detail='tampered' WHERE id=2")
        self.assertFalse(p.verify_chain(self.db))
        self.assertFalse(p.dashboard(self.db)["audit_chain_verified"])

    def test_actor_validation_failure_rolls_back_mutation(self):
        with self.assertRaisesRegex(p.ProductionError,"invalid_identifier"):
            p.create_project(self.db,"SHOW01","Original",actor="not a valid actor")
        self.assertEqual(p.dashboard(self.db)["counts"]["projects"],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM audit_chain").fetchone()[0],0)

    def test_read_only_database_snapshot_and_no_legacy_schema_migration(self):
        self.basic()
        with closing(p.open_db(self.path,initialize=False)) as read_only:
            self.assertEqual(p.dashboard(read_only)["counts"]["production_shots"],2)
            with self.assertRaises(sqlite3.OperationalError):
                read_only.execute("DELETE FROM projects")
        self.assertNotIn("shots", {r[0] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")})

    def test_cli_never_executes_without_explicit_review_confirmation(self):
        self.make_exception()
        result=cli.main(["--db",str(self.path),"decide-exception","--id","X01",
                         "--decision","approve","--expected-revision","1"])
        self.assertEqual(result,2)
        self.assertEqual(self.db.execute("SELECT status FROM exceptions").fetchone()[0],"draft")
        result=cli.main(["--db",str(self.path),"decide-exception","--id","X01",
                         "--decision","approve","--expected-revision","1",
                         "--i-reviewed-evidence"])
        self.assertEqual(result,0)

    def test_invalid_project_identifier_or_control_fields_rejected(self):
        with self.assertRaisesRegex(p.ProductionError,"invalid_identifier"):
            p.create_project(self.db,"../../etc/passwd","Unsafe")
        self.basic()
        with self.assertRaisesRegex(p.ProductionError,"invalid_continuity_attribute"):
            p.create_finding(self.db,"F01","SHOW01","EP01","S01",
                             "custom;drop table",HASH1,"invalid")


if __name__=="__main__":
    unittest.main()
