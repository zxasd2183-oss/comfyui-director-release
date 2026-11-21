"""Authorized bookmark route contract, all fake identities; no VPS access."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"vps-control"))
from glacier_bookmark_cas_store import BookmarkCASStore
from glacier_bookmark_api_router import create_bookmark_router
FIXTURE=ROOT/"glacier-android-gecko/app/src/androidTest/assets/glacier_bookmark_portable_work_v1.json"


def qa_session_user(request: Request):
    """ONLY a synthetic test dependency, not a production session verifier."""
    auth=request.headers.get("Authorization")
    if auth=="Bearer synthetic-device-A":
        return "verified-user-A"
    if auth=="Bearer synthetic-device-B":
        return "verified-user-B"
    raise HTTPException(401,detail="Unauthenticated device")


class BookmarkApiAuthContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=BookmarkCASStore(Path(self.tmp.name)/"encrypted-bookmarks.sqlite3")
        self.app=FastAPI()
        self.app.include_router(create_bookmark_router(self.store,qa_session_user))
        self.client=TestClient(self.app)
        self.fixture=json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.body={"expected_version":0,"envelope":self.fixture["envelope"]}
        self.a={"Authorization":"Bearer synthetic-device-A"}
        self.b={"Authorization":"Bearer synthetic-device-B"}

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_unverified_requests_are_denied(self):
        for method in ("get","put"):
            fn=getattr(self.client,method)
            response=fn("/v1/bookmarks/work",**({"json":self.body} if method=="put" else {}))
            self.assertEqual(response.status_code,401)

    def test_authenticated_account_isolation_and_cas(self):
        self.assertEqual(self.client.get("/v1/bookmarks/work",headers=self.a).json(),
                         {"version":0,"envelope":None})
        put=self.client.put("/v1/bookmarks/work",headers=self.a,json=self.body)
        self.assertEqual(put.status_code,200)
        self.assertEqual(put.json()["version"],1)
        self.assertEqual(self.client.get("/v1/bookmarks/work",headers=self.a).json(),
                         {"version":1,"envelope":self.fixture["envelope"]})
        self.assertEqual(self.client.get("/v1/bookmarks/work",headers=self.b).json()["version"],0)
        self.assertEqual(self.client.get("/v1/bookmarks/private",headers=self.a).json()["version"],0)
        repeat=self.client.put("/v1/bookmarks/work",headers=self.a,json=self.body)
        self.assertEqual(repeat.status_code,409)
        self.assertEqual(self.client.get("/v1/bookmarks/work",headers=self.a).json()["version"],1)

    def test_client_cannot_select_another_account_or_send_account_card_envelope(self):
        body=dict(self.body)
        body["user_id"]="verified-user-B"
        self.assertEqual(self.client.put("/v1/bookmarks/work",headers=self.a,json=body).status_code,422)
        self.assertEqual(self.client.get("/v1/bookmarks/work",headers=self.b).json()["version"],0)
        self.assertEqual(self.client.get("/v1/bookmarks/admin",headers=self.a).status_code,422)
        invalid=dict(self.body)
        altered=json.loads(self.fixture["envelope"])
        altered["format"]="glacier-vault-v1"
        invalid["envelope"]=json.dumps(altered)
        self.assertEqual(self.client.put("/v1/bookmarks/work",headers=self.a,json=invalid).status_code,422)
        self.assertEqual(self.client.get("/v1/bookmarks/work",headers=self.a).json()["version"],0)


if __name__=="__main__":
    unittest.main()
