"""V0.9.1 Web Microsoft owner sign-in security tests (offline fakes only)."""
from __future__ import annotations
import hashlib
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import studio_identity as identity
import studio_server as server


CFG={
    "client_id":"12345678-1234-1234-1234-123456789abc",
    "client_secret":"unit-test-only-secret-do-not-use",
    "owner_sub":"owner_subject_fixed_1234",
}


class FakeMSAL:
    def __init__(self):
        self.last=None
        self.calls=0
    def initiate_auth_code_flow(self, scopes, redirect_uri, response_mode, max_age):
        assert "openid" in scopes and redirect_uri == identity.REDIRECT
        assert response_mode == "query"
        self.calls+=1
        state="st"+str(self.calls).zfill(20)
        self.last={"state":state,"code_verifier":"v"*48,
                   "nonce":"unit-test-nonce-value-12345678",
                   "auth_uri":identity.AUTHORITY+"/oauth2/v2.0/authorize?state="+state}
        return dict(self.last)
    def acquire_token_by_auth_code_flow(self, flow, query):
        if flow["state"] != query["state"]:
            raise ValueError("mismatch")
        return {"id_token":"fake-signed-id-token"}


def fake_claims(app, *, subject=None, nonce=None, tenant=None):
    return {
        "tid":tenant or identity.PERSONAL_TID,
        "iss":identity.ISSUER, "aud":CFG["client_id"],
        "sub":subject or CFG["owner_sub"],
        "nonce":nonce or hashlib.sha256(app.last["nonce"].encode("ascii")).hexdigest(),
    }


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.app=FakeMSAL()
        self.now=[1000.0]
        self.claims=lambda token:fake_claims(self.app)
        self.id=identity.MicrosoftStudioIdentity(
            CFG,msal_app=self.app,validator=lambda tok:self.claims(tok),
            clock=lambda:self.now[0])

    def test_no_implicit_trust_from_any_microsoft_account(self):
        with self.assertRaisesRegex(identity.IdentityError,"owner_not_bound"):
            identity.MicrosoftStudioIdentity(
                {**CFG,"owner_sub":""},msal_app=self.app,validator=self.claims)
        with self.assertRaisesRegex(identity.IdentityError,"identity_config_invalid"):
            identity.MicrosoftStudioIdentity({**CFG,"debug":True},
                msal_app=self.app,validator=self.claims)

    def test_uses_pkce_nonce_state_and_owner_claims(self):
        uri,state=self.id.start()
        self.assertTrue(uri.startswith(identity.AUTHORITY+"/"))
        self.assertEqual(len(state),22)
        with self.assertRaisesRegex(identity.IdentityError,"state_invalid"):
            self.id.finish({"state":state,"code":"some-secure-auth-code"}, "bad_cookie")
        sid=self.id.finish({"state":state,"code":"some-secure-auth-code"},state)
        self.assertIsNotNone(self.id.check(sid))
        self.assertEqual(self.id.check(sid)["sub"],CFG["owner_sub"])
        with self.assertRaisesRegex(identity.IdentityError,"flow_expired"):
            self.id.finish({"state":state,"code":"some-secure-auth-code"},state)
        self.id.logout(sid)
        self.assertIsNone(self.id.check(sid))

    def test_wrong_owner_tenant_and_nonce_are_rejected(self):
        for overrides in [
            {"subject":"stranger_account_999999"},
            {"tenant":"organization-tenant"},
            {"nonce":"not-the-generated-nonce"},
        ]:
            uri,state=self.id.start()
            self.claims=lambda tok, over=overrides:fake_claims(self.app,**over)
            with self.assertRaisesRegex(identity.IdentityError,"owner_not_authorized"):
                self.id.finish({"state":state,"code":"some-secure-auth-code"},state)
            self.assertEqual(self.id.sessions,{})

    def test_expiry_and_idle_session_limits(self):
        _,state=self.id.start()
        self.now[0]+=identity.FLOW_TTL+1
        with self.assertRaisesRegex(identity.IdentityError,"flow_expired"):
            self.id.finish({"state":state,"code":"some-secure-auth-code"},state)
        _,state=self.id.start()
        sid=self.id.finish({"state":state,"code":"some-secure-auth-code"},state)
        self.now[0]+=identity.SESSION_IDLE+1
        self.assertIsNone(self.id.check(sid))
        _,state=self.id.start()
        sid=self.id.finish({"state":state,"code":"some-secure-auth-code"},state)
        for t in range(4):
            self.now[0]+=identity.SESSION_IDLE-1
            self.assertIsNotNone(self.id.check(sid))
        self.now[0]+=identity.SESSION_TTL
        self.assertIsNone(self.id.check(sid))

    def test_secure_cookie_attributes_and_config_fail_closed(self):
        self.assertIn("Secure; HttpOnly; SameSite=Lax",identity.session_cookie("s"*43))
        self.assertIn("Path=/studio/",identity.state_cookie("st"+"0"*20))
        self.assertIsNone(identity.load_systemd_config({"CREDENTIALS_DIRECTORY":""}))
        self.assertEqual(identity.cookies("a=b; x=c"),{"a":"b","x":"c"})
        self.assertEqual(identity.cookies("a="+"x"*10000),{})

    def test_invalid_msal_response_does_not_fallback_to_weak_login(self):
        class NoPKCE(FakeMSAL):
            def initiate_auth_code_flow(self,*a,**kw):
                d=super().initiate_auth_code_flow(*a,**kw)
                d.pop("code_verifier")
                return d
        a=NoPKCE()
        service=identity.MicrosoftStudioIdentity(CFG,msal_app=a,validator=self.claims)
        with self.assertRaisesRegex(identity.IdentityError,"pkce_preflight_failed"):
            service.start()


class SSOHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake=FakeMSAL()
        self.id=identity.MicrosoftStudioIdentity(
            CFG,msal_app=self.fake,
            validator=lambda token:fake_claims(self.fake))
        self.svc=server.StudioServer(self.tmp.name+"/studio.sqlite",
            poller=server.Poller(probe=lambda tool:{"ok":False,"reason":"test"}),bind=("127.0.0.1",0))
        self.svc.identity=self.id
        self.thread=threading.Thread(target=self.svc.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.svc.shutdown()
        self.svc.server_close()
        self.thread.join(3)

    def ask(self,method,path,body=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.svc.server_port,timeout=4)
        headers={"Host":"127.0.0.1:8900",
                 "X-Forwarded-Proto":"https",
                 "X-Forwarded-Host":"jipite.borealos.cn",
                 "X-Director-Studio-Auth-Mode":"microsoft",
                 **(headers or {})}
        data=json.dumps(body).encode() if body is not None else None
        conn.request(method,path,data,headers=headers)
        resp=conn.getresponse()
        raw=resp.read()
        out={"status":resp.status,"location":resp.getheader("Location"),
             "cookies":resp.getheaders("Set-Cookie"),
             "json":json.loads(raw) if raw and "application/json" in resp.getheader("Content-Type","") else None}
        conn.close()
        return out

    def login(self):
        begin=self.ask("GET","/auth/start")
        self.assertEqual(begin["status"],302)
        state=self.fake.last["state"]
        self.assertIn(identity.COOKIE_STATE,begin["cookies"][0])
        finish=self.ask("GET","/auth/callback?state="+quote(state)+"&code="+quote("some-secure-auth-code"),
                        headers={"Cookie":identity.COOKIE_STATE+"="+state})
        self.assertEqual(finish["status"],302)
        self.assertEqual(finish["location"],"/studio/")
        sid=next(cookie.split("=",1)[1].split(";",1)[0] for cookie in finish["cookies"]
                 if cookie.startswith(identity.COOKIE_SID+"="))
        return sid,state

    def test_public_route_blocks_everything_before_login(self):
        self.assertEqual(self.ask("GET","/")["location"],"/studio/auth/start")
        self.assertEqual(self.ask("GET","/api/v1/snapshot")["status"],401)
        self.assertEqual(self.ask("GET","/api/v1/production")["status"],401)
        self.assertEqual(self.ask("GET","/studio.js")["status"],401)
        self.assertEqual(self.ask("GET","/api/v1/bootstrap")["status"],401)
        self.assertEqual(self.ask("GET","/auth/status")["json"]["authenticated"],False)
        req=self.ask("POST","/api/v1/action",{"action":"resume_dispatch"},
                     {"Origin":"https://jipite.borealos.cn","Content-Type":"application/json"})
        self.assertEqual(req["status"],401)

    def test_complete_login_session_scoped_csrf_and_logout(self):
        sid,state=self.login()
        header={"Cookie":identity.COOKIE_SID+"="+sid}
        self.assertEqual(self.ask("GET","/auth/status",headers=header)["json"]["authenticated"],True)
        boot=self.ask("GET","/api/v1/bootstrap",headers=header)
        self.assertEqual(boot["json"]["mode"],"microsoft_owner")
        self.assertEqual(self.ask("GET","/api/v1/snapshot",headers=header)["status"],200)
        wrong=self.ask("POST","/api/v1/action",{
            "csrf":"wrong","action":"resume_dispatch"},{
                **header,"Origin":"https://jipite.borealos.cn",
                "Content-Type":"application/json"})
        self.assertEqual(wrong["status"],403)
        good=self.ask("POST","/api/v1/action",{
            "csrf":boot["json"]["csrf"],"action":"pause_dispatch"},{
                **header,"Origin":"https://jipite.borealos.cn",
                "Content-Type":"application/json"})
        self.assertEqual(good["status"],200)
        self.assertFalse(good["json"]["executed_on_gpu"])
        self.assertEqual(self.ask("POST","/auth/logout",headers={
            **header,"Origin":"https://jipite.borealos.cn",
            "X-CSRF-Token":"wrong"})["status"],403)
        quit=self.ask("POST","/auth/logout",headers={
            **header,"Origin":"https://jipite.borealos.cn",
            "X-CSRF-Token":boot["json"]["csrf"]})
        self.assertEqual(quit["status"],204)
        self.assertEqual(self.ask("GET","/api/v1/snapshot",headers=header)["status"],401)

    def test_public_proxy_fails_closed_without_identity_or_tls_markers(self):
        self.svc.identity=None
        self.assertEqual(self.ask("GET","/api/v1/snapshot")["status"],503)
        self.assertEqual(self.ask("GET","/")["status"],503)
        self.assertEqual(self.ask("GET","/api/v1/snapshot",headers={
            "X-Forwarded-Proto":"http"})["status"],403)
        self.assertEqual(self.ask("POST","/api/v1/action",{"action":"pause_dispatch"},
            headers={"Origin":"https://jipite.borealos.cn"})["status"],503)

    def test_local_ssh_ui_remains_functional_without_auth_marker(self):
        result=self.ask("GET","/api/v1/snapshot",headers={
            "X-Forwarded-Proto":"","X-Forwarded-Host":"",
            "X-Director-Studio-Auth-Mode":""})
        self.assertEqual(result["status"],200)

    def test_replayed_callback_or_wrong_state_cookie_denied(self):
        self.ask("GET","/auth/start")
        state=self.fake.last["state"]
        url="/auth/callback?state="+state+"&code=some-secure-auth-code"
        self.assertEqual(self.ask("GET",url,headers={
            "Cookie":identity.COOKIE_STATE+"=not-the-correct-state"})["status"],403)
        self.assertEqual(self.ask("GET",url,headers={
            "Cookie":identity.COOKIE_STATE+"="+state})["status"],302)
        self.assertEqual(self.ask("GET",url,headers={
            "Cookie":identity.COOKIE_STATE+"="+state})["status"],403)


if __name__ == "__main__":
    unittest.main()
