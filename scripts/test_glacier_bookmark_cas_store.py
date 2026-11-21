"""Isolated bookmark CAS backend: encrypted-only, concurrency and per-user isolation."""
import importlib.util
import json
import pathlib
import sqlite3
import tempfile
import threading
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
PATH=ROOT/"vps-control/glacier_bookmark_cas_store.py"
SPEC=importlib.util.spec_from_file_location("glacier_bookmark_store_v1",PATH)
storemod=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(storemod)
FIXTURE=ROOT/"glacier-android-gecko/app/src/androidTest/assets/glacier_bookmark_portable_work_v1.json"


class BookmarkStoreContract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=pathlib.Path(self.temp.name)/"bookmarks.sqlite3"
        self.store=storemod.BookmarkCASStore(self.db)
        self.fixture=json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.envelope=self.fixture["envelope"]

    def tearDown(self):
        self.temp.cleanup()

    def test_authenticated_user_and_spaces_are_isolated(self):
        self.assertEqual(self.store.get("user-A","private"),
                         {"version":0,"envelope":None})
        self.assertEqual(self.store.put("user-A","work",0,self.envelope),
                         {"version":1})
        self.assertEqual(self.store.get("user-A","work")["envelope"],self.envelope)
        self.assertEqual(self.store.get("user-A","private")["version"],0)
        self.assertEqual(self.store.get("user-B","work")["version"],0)
        self.assertEqual(self.store.put("user-B","work",0,self.envelope),
                         {"version":1})
        for unsafe in ("", "user/id", "nonascii-用户", "x"*129):
            with self.assertRaises(storemod.BookmarkStoreError):
                self.store.get(unsafe,"work")
        with self.assertRaises(storemod.BookmarkStoreError):
            self.store.get("user-A","credentials")

    def test_conflict_and_rollback_never_replace_server_record(self):
        self.store.put("alpha","work",0,self.envelope)
        after=self.store.put("alpha","work",1,self.envelope)
        self.assertEqual(after["version"],2)
        with self.assertRaises(storemod.BookmarkConflict):
            self.store.put("alpha","work",1,self.envelope)
        with self.assertRaises(storemod.BookmarkConflict):
            self.store.put("alpha","work",0,self.envelope)
        self.assertEqual(self.store.get("alpha","work")["version"],2)

    def test_plaintext_is_not_stored_or_returned_by_database(self):
        self.store.put("alpha","work",0,self.envelope)
        with sqlite3.connect(self.db) as db:
            raw=db.execute("SELECT envelope FROM glacier_e2e_bookmarks_v1").fetchone()[0]
            self.assertEqual(raw,self.envelope)
            self.assertNotIn("Glacier 示例工作站",raw)
            self.assertNotIn("work.example.org",raw)
            self.assertNotIn(self.fixture["passphrase"],raw)

    def test_two_writers_same_version_only_one_success(self):
        barrier=threading.Barrier(2)
        outcomes=[]
        def worker():
            barrier.wait(timeout=6)
            try:
                self.store.put("alpha","work",0,self.envelope)
                return "uploaded"
            except storemod.BookmarkConflict:
                return "conflict"
        with __import__("concurrent.futures").futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(lambda _:worker(),range(2)))
        self.assertEqual(sorted(outcomes),["conflict","uploaded"])
        self.assertEqual(self.store.get("alpha","work")["version"],1)

    def test_unsupported_envelopes_are_rejected_without_write(self):
        bad=json.loads(self.envelope)
        bad["format"]="glacier-vault-v1"  # account secrets are separate.
        for invalid in (json.dumps(bad),"{}","not-json",
                        self.envelope+"x"*350000):
            with self.assertRaises(storemod.BookmarkStoreError):
                self.store.put("alpha","work",0,invalid)
        with self.assertRaises(storemod.BookmarkStoreError):
            self.store.put("alpha","work",True,self.envelope)
        self.assertEqual(self.store.get("alpha","work")["version"],0)


if __name__=="__main__":
    unittest.main()
