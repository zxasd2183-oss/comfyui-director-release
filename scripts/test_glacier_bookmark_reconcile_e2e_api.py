"""Full synthetic HTTP contract: bookmark client -> existing-session-injected API.

Uses an in-process FastAPI TestClient, a throwaway SQLite file, fake users and
synthetic bookmark URLs. No live VPS, tokens, network proxies or user files.
"""
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import unittest

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"vps-control"))
sys.path.insert(0,str(ROOT/"glacier-windows"))
from glacier_bookmark_cas_store import BookmarkCASStore
from glacier_bookmark_api_router import create_bookmark_router
from glacier_bookmark_sync_v1 import first_sync, reconcile, accept_download, BookmarkSyncError

PASS="synthetic-bookmark-passphrase-2026"
SPACE="work"
BASE="https://sync.borealos.cn"
A=BASE+"|qa-user-a"


def fake_verified_session(request: Request):
    token=request.headers.get("Authorization","")
    if token=="Bearer synthetic-device-user-a":
        return "qa-user-a"
    if token=="Bearer synthetic-device-user-b":
        return "qa-user-b"
    raise HTTPException(401,detail="No authenticated session")


class HttpTransport:
    def __init__(self,testclient,token):
        self.client=testclient
        self.headers={"Authorization":"Bearer "+token}
        self.routes=[]
    def call(self,method,path,data=None):
        self.routes.append((method,path))
        if not path.startswith("/v1/bookmarks/"):
            raise AssertionError("Browser account-card vault route MUST NOT be used")
        if method=="GET":result=self.client.get(path,headers=self.headers)
        elif method=="PUT":result=self.client.put(path,headers=self.headers,json=data)
        else:raise AssertionError("Unsupported method")
        if result.status_code>=400:
            raise BookmarkSyncError("Simulated Glacier Sync HTTP "+str(result.status_code))
        return result.json()


class EndToEndBookmarkSessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=BookmarkCASStore(Path(self.tmp.name)/"bookmarks.sqlite")
        self.app=FastAPI()
        self.app.include_router(create_bookmark_router(self.db,fake_verified_session))
        self.client=TestClient(self.app)
        self.one=HttpTransport(self.client,"synthetic-device-user-a")
        self.two=HttpTransport(self.client,"synthetic-device-user-a")
        self.other=HttpTransport(self.client,"synthetic-device-user-b")
        self.rows=[{"profile":"work","title":"Guide",
                    "url":"https://work.example.org/guide","at":1795000000000}]
        self.nextrow={"profile":"work","title":"Read",
                      "url":"https://work.example.org/read","at":1795000000001}

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_authorized_first_sync_then_incremental_import_and_additive_upload(self):
        self.assertEqual(reconcile(self.one,A,SPACE,self.rows,None,PASS)["kind"],
                         "uninitialized")
        self.assertEqual(self.one.routes,[])
        first=first_sync(self.one,A,SPACE,self.rows,PASS,choice="upload")
        self.assertEqual(first["version"],1)
        self.assertEqual(self.db.get("qa-user-a","work")["version"],1)
        self.assertEqual(self.db.get("qa-user-b","work")["version"],0)
        second=first_sync(self.two,A,SPACE,[],PASS,choice="download")
        self.assertEqual(second["kind"],"download_pending")
        self.assertEqual(len(second["records"]),1)
        approved=accept_download(second,A,SPACE,[])
        changed=approved["records"]+[self.nextrow]
        update=reconcile(self.two,A,SPACE,changed,approved["checkpoint"],PASS)
        self.assertEqual(update["kind"],"uploaded")
        self.assertEqual(self.db.get("qa-user-a","work")["version"],2)
        incoming=reconcile(self.one,A,SPACE,self.rows,first["checkpoint"],PASS)
        self.assertEqual(incoming["kind"],"download_pending")
        self.assertEqual(len(accept_download(incoming,A,SPACE,self.rows)["records"]),2)
        self.assertEqual(self.db.get("qa-user-a","private")["version"],0)

    def test_no_client_chosen_user_id_and_no_unauthorized_download(self):
        response=self.client.get("/v1/bookmarks/work")
        self.assertEqual(response.status_code,401)
        body={"expected_version":0,"envelope":"not-an-envelope","user_id":"qa-user-a"}
        self.assertEqual(self.client.put("/v1/bookmarks/work",headers=self.other.headers,
                                         json=body).status_code,422)
        first=first_sync(self.one,A,SPACE,self.rows,PASS,choice="upload")
        self.assertEqual(self.other.call("GET","/v1/bookmarks/work"),
                         {"version":0,"envelope":None})
        self.assertEqual(self.db.get("qa-user-b","work")["version"],0)
        self.assertEqual(first["kind"],"uploaded")

    def test_conflicting_cloud_write_does_not_mutate_local_or_checkpoint(self):
        first=first_sync(self.one,A,SPACE,self.rows,PASS,choice="upload")
        baseline=first["checkpoint"]
        someone=first_sync(self.two,A,SPACE,[],PASS,choice="download")
        accepted=accept_download(someone,A,SPACE,[])
        remote_rows=accepted["records"]+[self.nextrow]
        reconcile(self.two,A,SPACE,remote_rows,accepted["checkpoint"],PASS)
        local_changed=self.rows+[{"profile":"work","title":"Other",
                       "url":"https://work.example.org/other","at":1795000000002}]
        result=reconcile(self.one,A,SPACE,local_changed,baseline,PASS)
        self.assertEqual(result["kind"],"conflict")
        self.assertEqual(self.db.get("qa-user-a","work")["version"],2)
        self.assertEqual(baseline["version"],1)
        self.assertEqual(len(local_changed),2)


if __name__=="__main__":
    unittest.main()
