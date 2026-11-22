"""Glacier opt-in bookmark reconcile with fake server, no network/user data."""
import importlib.util
import pathlib
import unittest
from unittest.mock import Mock

ROOT=pathlib.Path(__file__).resolve().parents[1]
SAMPLE=[
    {"profile":"work","title":"Docs","url":"https://docs.example.org/guide","at":1795000000001},
    {"profile":"work","title":"Work","url":"https://work.example.org/a","at":1795000000002},
]
EXTRA={"profile":"work","title":"Third","url":"https://work.example.org/new","at":1795000000003}
OWNER="https://sync.borealos.cn|verified-test-user"
SECRET="synthetic-bookmark-passphrase-2026"


def load(platform):
    codecfile=ROOT/f"glacier-{platform}/glacier_bookmark_portable_v1.py"
    coordfile=ROOT/f"glacier-{platform}/glacier_bookmark_sync_v1.py"
    import sys
    sys.path.insert(0,str(codecfile.parent))
    for path,name in [(codecfile,f"glacier_bookmark_portable_v1_{platform}"),
                      (coordfile,f"glacier_bookmark_sync_v1_{platform}")]:
        spec=importlib.util.spec_from_file_location(name,path)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if path==codecfile: codec=module
        else: coord=module
    sys.path.pop(0)
    return codec,coord


class FakeCAS:
    def __init__(self):
        self.version=0
        self.envelope=None
        self.calls=[]

    def call(self, method, path, data=None):
        if path!="/v1/bookmarks/work":
            raise AssertionError("Unexpected endpoint (account-card vault must not be touched)")
        self.calls.append((method,path))
        if method=="GET":
            return {"version":self.version,"envelope":self.envelope}
        if method!="PUT":
            raise AssertionError("Unsupported mutation")
        if data.get("expected_version")!=self.version:
            raise RuntimeError("HTTP 409 optimistic concurrency conflict")
        self.version+=1
        self.envelope=data["envelope"]
        return {"version":self.version}


class BookmarksClientReconcileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clients={p:load(p) for p in ("windows","macos")}

    def test_exactly_identical_portable_client_code(self):
        self.assertEqual((ROOT/"glacier-windows/glacier_bookmark_sync_v1.py").read_bytes(),
                         (ROOT/"glacier-macos/glacier_bookmark_sync_v1.py").read_bytes())

    def test_first_upload_requires_explicit_consent_and_only_empty_cloud(self):
        for platform,(_,client) in self.clients.items():
            with self.subTest(platform=platform):
                srv=FakeCAS()
                self.assertEqual(client.reconcile(srv,OWNER,"work",SAMPLE,None,SECRET),
                                 {"kind":"uninitialized"})
                self.assertEqual(srv.calls,[])
                with self.assertRaises(client.BookmarkSyncError):
                    client.first_sync(srv,OWNER,"work",SAMPLE,SECRET,choice="auto")
                created=client.first_sync(srv,OWNER,"work",SAMPLE,SECRET,choice="upload")
                self.assertEqual(created["kind"],"uploaded")
                self.assertEqual(srv.version,1)
                self.assertEqual(srv.calls,[("GET","/v1/bookmarks/work"),("PUT","/v1/bookmarks/work")])
                with self.assertRaises(client.BookmarkSyncError):
                    client.first_sync(srv,OWNER,"work",SAMPLE,SECRET,choice="upload")

    def test_desktop_a_upload_then_desktop_b_safe_import_and_merge(self):
        for platform,(_,client) in self.clients.items():
            srv=FakeCAS()
            baseline=client.first_sync(srv,OWNER,"work",SAMPLE,SECRET,choice="upload")["checkpoint"]
            # The same local device adds a bookmark; CAS upload only if cloud stayed unchanged.
            changed=SAMPLE+[EXTRA]
            res=client.reconcile(srv,OWNER,"work",changed,baseline,SECRET)
            self.assertEqual(res["kind"],"uploaded")
            self.assertEqual(srv.version,2)
            local_b=[{"profile":"work","title":"Keep my title","url":SAMPLE[0]["url"],"at":42}]
            b=client.first_sync(srv,OWNER,"work",local_b,SECRET,choice="download")
            self.assertEqual(b["kind"],"download_pending")
            self.assertEqual(len(local_b),1)
            approved=client.accept_download(b,OWNER,"work",local_b)
            self.assertEqual(len(approved["records"]),3)
            self.assertEqual(approved["records"][0]["title"],"Keep my title")
            self.assertEqual(client.reconcile(srv,OWNER,"work",approved["records"],
                                              approved["checkpoint"],SECRET)["kind"],"unchanged")

    def test_cloud_update_is_pending_until_current_local_hash_rechecked(self):
        for platform,(_,client) in self.clients.items():
            srv=FakeCAS()
            a=client.first_sync(srv,OWNER,"work",SAMPLE,SECRET,choice="upload")
            c=a["checkpoint"]
            srv.version+=1
            srv.envelope=self.clients["windows"][0].encrypt_bookmarks("work",SAMPLE+[EXTRA],SECRET)
            pending=client.reconcile(srv,OWNER,"work",SAMPLE,c,SECRET)
            self.assertEqual(pending["kind"],"download_pending")
            self.assertEqual(len(pending["records"]),3)
            with self.assertRaises(client.BookmarkSyncError):
                client.accept_download(pending,OWNER,"work",SAMPLE+[EXTRA])
            result=client.accept_download(pending,OWNER,"work",SAMPLE)
            self.assertEqual(len(result["records"]),3)

    def test_concurrent_change_detects_conflict_rollback_and_ciphertext_tamper(self):
        for platform,(_,client) in self.clients.items():
            srv=FakeCAS()
            baseline=client.first_sync(srv,OWNER,"work",SAMPLE,SECRET,choice="upload")["checkpoint"]
            srv.version+=1
            srv.envelope=self.clients["windows"][0].encrypt_bookmarks("work",SAMPLE+[EXTRA],SECRET)
            self.assertEqual(client.reconcile(srv,OWNER,"work",SAMPLE+[EXTRA],baseline,SECRET)["kind"],"conflict")
            srv.version=0
            srv.envelope=None
            self.assertEqual(client.reconcile(srv,OWNER,"work",SAMPLE,baseline,SECRET)["kind"],"rollback")
            srv.version=1
            srv.envelope=self.clients["windows"][0].encrypt_bookmarks("work",SAMPLE+[EXTRA],SECRET)
            self.assertEqual(client.reconcile(srv,OWNER,"work",SAMPLE,baseline,SECRET)["kind"],"tampered")

    def test_no_cross_account_checkpoint_or_unauthorized_remote_upload(self):
        for platform,(_,client) in self.clients.items():
            srv=FakeCAS()
            initial=client.first_sync(srv,OWNER,"work",SAMPLE,SECRET,choice="upload")
            with self.assertRaises(client.BookmarkSyncError):
                client.reconcile(srv,OWNER+"-different","work",SAMPLE,
                                 initial["checkpoint"],SECRET)
            self.assertEqual(srv.version,1)

    def test_offline_and_bad_server_response_do_not_change_local_state(self):
        for platform,(_,client) in self.clients.items():
            srv=FakeCAS()
            baseline=client.first_sync(srv,OWNER,"work",SAMPLE,SECRET,choice="upload")["checkpoint"]
            class Offline:
                def call(self,*args):
                    raise OSError("No VLESS; no direct fallback")
            with self.assertRaises(OSError):
                client.reconcile(Offline(),OWNER,"work",SAMPLE,baseline,SECRET)
            srv.version=True
            with self.assertRaises(client.BookmarkSyncError):
                client.reconcile(srv,OWNER,"work",SAMPLE,baseline,SECRET)
            self.assertEqual(len(SAMPLE),2)


if __name__=="__main__":
    unittest.main()
