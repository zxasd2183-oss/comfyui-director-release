"""V0.9.1 Web Microsoft owner sign-in security tests (offline fakes only)."""
from __future__ import annotations
import hashlib
import io
import http.client
from contextlib import redirect_stdout
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
        assert scopes == [] and redirect_uri == identity.REDIRECT
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


class CallbackDiagnosticTests(unittest.TestCase):
    def test_logs_only_known_param_names_never_values_or_untrusted_keys(self):
        secret = "secret-auth-code-super-confidential"
        payload = ("code="+secret+"&state=some-state&error_description="
                   "private-user-email&access_token=TOP-SECRET-TOKEN")
        msg=server.callback_fields_for_log(payload)
        self.assertIn("param_names=code,error_description,state,other",msg)
        self.assertIn("param_count=4",msg)
        self.assertIn("unknown_count=1",msg)
        self.assertNotIn(secret,msg)
        self.assertNotIn("private-user-email",msg)
        self.assertNotIn("access_token",msg)
        self.assertNotIn("TOP-SECRET-TOKEN",msg)

    def test_error_callback_and_duplicate_keys_identified(self):
        msg=server.callback_fields_for_log(
            "error=access_denied&error_description=secret&state=abc")
        self.assertIn("param_names=error,error_description,state",msg)
        self.assertIn("param_count=3",msg)
        self.assertNotIn("access_denied",msg)
        self.assertNotIn("secret",msg)
        # Known diagnostic names are not necessarily accepted as auth inputs.
        self.assertIn("unknown_count=0",msg)
        self.assertIn("unsupported_count=2",msg)
        supported=server.callback_fields_for_log(
            "code=PRIVATE&state=STATE&client_info=eyJ1aWQiOiJ0ZXN0In0")
        self.assertIn("unsupported_count=0",supported)
        self.assertNotIn("PRIVATE",supported)
        msg=server.callback_fields_for_log("code=x&state=y&state=z")
        self.assertIn("duplicates=1",msg)

    def test_malicious_parameter_names_are_not_logged(self):
        msg=server.callback_fields_for_log(
            "code=x&state=y&%0AFAKE-LOG%20TOKEN%3Dabc=value")
        self.assertIn("other",msg)
        self.assertNotIn("FAKE-LOG",msg)
        self.assertNotIn("TOKEN",msg)
        self.assertNotIn("\\n",msg)

    def test_long_parameter_query_is_bounded(self):
        msg=server.callback_fields_for_log(
            "&".join("unknown"+str(i)+"=secret" for i in range(33)))
        self.assertIn("too_many",msg)
        self.assertNotIn("secret",msg)
        msg=server.callback_fields_for_log("code="+"S"*17000)
        self.assertIn("oversized",msg)
        self.assertNotIn("S"*64,msg)


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

    def test_microsoft_callback_may_include_session_state(self):
        _,state=self.id.start()
        sid=self.id.finish({"state":state,"code":"some-secure-auth-code",
            "session_state":"8a2b6c3d-1111-2222-3333-444455556666"},state)
        self.assertEqual(self.id.check(sid)["sub"],CFG["owner_sub"])

    def test_real_microsoft_callback_accepts_client_info(self):
        _,state=self.id.start()
        info="eyJ1aWQiOiJ0ZXN0IiwidXRpZCI6InRlc3QifQ"
        sid=self.id.finish({"state":state,"code":"some-secure-auth-code",
                            "client_info":info},state)
        self.assertEqual(self.id.check(sid)["sub"],CFG["owner_sub"])

    def test_callback_accepts_both_optional_microsoft_parameters(self):
        _,state=self.id.start()
        sid=self.id.finish({"state":state,"code":"some-secure-auth-code",
                            "client_info":"eyJ1aWQiOiJ0ZXN0In0",
                            "session_state":"8a2b6c3d-1111-2222-3333-444455556666"},state)
        self.assertIsNotNone(self.id.check(sid))

    def test_client_info_must_remain_bounded_and_encoded(self):
        _,state=self.id.start()
        for invalid in ("short", "bad;newline", "x"*4100, "☃"):
            with self.subTest(value=str(invalid)[:20]):
                with self.assertRaisesRegex(identity.IdentityError,"state_invalid"):
                    self.id.finish({"state":state,"code":"some-secure-auth-code",
                                    "client_info":invalid},state)
        # Rejected input never consumes a valid authorization code flow.
        sid=self.id.finish({"state":state,"code":"some-secure-auth-code"},state)
        self.assertIsNotNone(self.id.check(sid))

    def test_microsoft_callback_rejects_extra_or_invalid_fields(self):
        _,state=self.id.start()
        with self.assertRaisesRegex(identity.IdentityError,"state_invalid"):
            self.id.finish({"state":state,"code":"some-secure-auth-code",
                            "session_state":"x;bad"},state)
        with self.assertRaisesRegex(identity.IdentityError,"state_invalid"):
            self.id.finish({"state":state,"code":"some-secure-auth-code",
                            "unexpected":"value"},state)
        # Failed basic validation must not consume an otherwise valid flow.
        sid=self.id.finish({"state":state,"code":"some-secure-auth-code"},state)
        self.assertIsNotNone(self.id.check(sid))

    def test_token_exchange_exception_is_not_misclassified_as_jwt_failure(self):
        class ExchangeFailure(FakeMSAL):
            def acquire_token_by_auth_code_flow(self, flow, query):
                raise RuntimeError("sensitive-authorization-code-should-never-appear")
        app=ExchangeFailure()
        identity_service=identity.MicrosoftStudioIdentity(
            CFG,msal_app=app,validator=lambda _:fake_claims(app))
        _,state=identity_service.start()
        with self.assertRaises(identity.IdentityError) as caught:
            identity_service.finish(
                {"state":state,"code":"some-secure-auth-code"},state)
        self.assertEqual(str(caught.exception),"microsoft_token_exchange_failed")
        self.assertEqual(caught.exception.diagnostic,"RuntimeError")
        self.assertNotIn("sensitive-",str(caught.exception))

    def test_jwt_invalid_issuer_category_and_no_token_data(self):
        from jwt.exceptions import InvalidIssuerError
        self.id.validate=lambda token:(_ for _ in ()).throw(
            InvalidIssuerError("secret-token-value-should-not-appear"))
        _,state=self.id.start()
        with self.assertRaises(identity.IdentityError) as caught:
            self.id.finish({"state":state,"code":"some-secure-auth-code"},state)
        self.assertEqual(str(caught.exception),"microsoft_token_verification_failed")
        self.assertEqual(caught.exception.diagnostic,"InvalidIssuerError")
        self.assertNotIn("secret-token",str(caught.exception))

    def test_missing_id_token_is_distinct_from_exchange_and_remains_denied(self):
        class MissingToken(FakeMSAL):
            def acquire_token_by_auth_code_flow(self, flow, query):
                return {"id_token_claims":{"sub":"fake"}}
        app=MissingToken()
        identity_service=identity.MicrosoftStudioIdentity(
            CFG,msal_app=app,validator=lambda _:"unexpected")
        _,state=identity_service.start()
        with self.assertRaises(identity.IdentityError) as caught:
            identity_service.finish(
                {"state":state,"code":"some-secure-auth-code"},state)
        self.assertEqual(str(caught.exception),"microsoft_token_verification_failed")
        self.assertEqual(caught.exception.diagnostic,"MissingIdToken")
        self.assertEqual(identity_service.sessions,{})

    def test_unknown_exception_name_maps_to_constant_safe_class(self):
        class SecretTokenWasCompromised(Exception):pass
        self.id.validate=lambda token:(_ for _ in ()).throw(
            SecretTokenWasCompromised("PII email@example.com"))
        _,state=self.id.start()
        with self.assertRaises(identity.IdentityError) as caught:
            self.id.finish({"state":state,"code":"some-secure-auth-code"},state)
        self.assertEqual(caught.exception.diagnostic,"OtherVerificationError")
        self.assertNotIn("email@example.com",str(caught.exception))

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
             "cookies":[value for key,value in resp.getheaders() if key.lower()=="set-cookie"],
             "json":json.loads(raw) if raw and "application/json" in resp.getheader("Content-Type","") else None,
             "body":raw.decode("utf-8","replace"),
             "content_type":resp.getheader("Content-Type","")}
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
        page=self.ask("GET","/")
        self.assertEqual(page["status"],200)
        self.assertIn("text/html",page["content_type"])
        self.assertIn("Director Studio",page["body"])
        self.assertIn("href=\"./auth/start\"",page["body"])
        self.assertNotIn("studio.js",page["body"])
        self.assertEqual(self.ask("GET","/login")["status"],200)
        self.assertEqual(self.ask("GET","/login.css")["status"],200)
        self.assertEqual(self.ask("GET","/api/v1/snapshot")["status"],401)
        self.assertEqual(self.ask("GET","/api/v1/production")["status"],401)
        self.assertEqual(self.ask("GET","/studio.js")["status"],401)
        self.assertEqual(self.ask("GET","/api/v1/bootstrap")["status"],401)
        self.assertEqual(self.ask("GET","/auth/status")["json"]["authenticated"],False)
        req=self.ask("POST","/api/v1/action",{"action":"resume_dispatch"},
                     {"Origin":"https://jipite.borealos.cn","Content-Type":"application/json"})
        self.assertEqual(req["status"],401)

    def test_glacier_login_public_content_has_no_private_data_or_external_scripts(self):
        page=self.ask("GET","/")
        self.assertEqual(page["status"],200)
        for word in ("导演专属工作空间", "欢迎回来，导演",
                     "进入 Director Studio","./login.css"):
            self.assertIn(word,page["body"])
        self.assertNotIn("window.location",page["body"])
        self.assertNotIn("<script",page["body"])
        self.assertNotIn("client_secret",page["body"])
        self.assertNotIn("owner_sub",page["body"])
        self.assertNotIn("https://login.microsoftonline.com/",page["body"])
        start=self.ask("GET","/auth/start")
        self.assertEqual(start["status"],302)
        self.assertTrue(start["location"].startswith(identity.AUTHORITY+"/"))
        self.assertEqual(self.ask("GET","/api/v1/production")["status"],401)
        self.assertEqual(self.ask("GET","/studio.css")["status"],401)
        self.assertEqual(self.ask("GET","/studio.js")["status"],401)

    def test_ssh_only_mode_keeps_original_dashboard_not_public_login(self):
        headers={"X-Forwarded-Proto":"",
                 "X-Forwarded-Host":"",
                 "X-Director-Studio-Auth-Mode":""}
        page=self.ask("GET","/",headers=headers)
        self.assertEqual(page["status"],200)
        self.assertIn("Production Control",page["body"])
        self.assertNotIn("WELCOME BACK",page["body"])
        self.assertEqual(self.ask("GET","/login",headers=headers)["status"],404)

    def test_real_jwt_exception_is_logged_as_class_only(self):
        from jwt.exceptions import InvalidIssuerError
        self.id.validate=lambda token:(_ for _ in ()).throw(
            InvalidIssuerError("DO-NOT-LOG-ID-TOKEN OR EMAIL"))
        self.ask("GET","/auth/start")
        state=self.fake.last["state"]
        callback="/auth/callback?state="+state+"&code=some-secure-auth-code"
        sink=io.StringIO()
        with redirect_stdout(sink):
            result=self.ask("GET",callback,headers={
                "Cookie":identity.COOKIE_STATE+"="+state})
        self.assertEqual(result["status"],403)
        self.assertEqual(result["json"]["reason"],"microsoft_login_failed")
        log=sink.getvalue()
        self.assertIn(
            "STUDIO_AUTH_CALLBACK_DENIED microsoft_token_verification_failed "
            "exc_class=InvalidIssuerError",log)
        self.assertNotIn("DO-NOT-LOG",log)
        self.assertNotIn("some-secure-auth-code",log)
        self.assertNotIn(state,log)
        self.assertNotIn("email",log.lower())
        self.assertEqual(self.id.sessions,{})

    def test_oauth_exchange_failure_logs_separately_without_credentials(self):
        def rejected(flow,query):
            raise RuntimeError("PRIVATE_CREDENTIAL_DO_NOT_LOG")
        self.fake.acquire_token_by_auth_code_flow=rejected
        self.ask("GET","/auth/start")
        state=self.fake.last["state"]
        sink=io.StringIO()
        with redirect_stdout(sink):
            result=self.ask(
                "GET","/auth/callback?state="+state+"&code=some-secure-auth-code",
                headers={"Cookie":identity.COOKIE_STATE+"="+state})
        self.assertEqual(result["status"],403)
        self.assertIn(
            "microsoft_token_exchange_failed exc_class=RuntimeError",
            sink.getvalue())
        self.assertNotIn("PRIVATE_CREDENTIAL_DO_NOT_LOG",sink.getvalue())
        self.assertEqual(self.id.sessions,{})

    def test_browser_callback_with_session_state_succeeds(self):
        start=self.ask("GET","/auth/start")
        self.assertEqual(start["status"],302)
        state=self.fake.last["state"]
        qs="/auth/callback?code=some-secure-auth-code&session_state=some-opaque-session-state-123456&state="+state
        result=self.ask("GET",qs,headers={"Cookie":identity.COOKIE_STATE+"="+state})
        self.assertEqual(result["status"],302)
        self.assertEqual(result["location"],"/studio/")
        self.assertTrue(any(k.startswith(identity.COOKIE_SID+"=") for k in result["cookies"]))

    def test_browser_callback_with_client_info_succeeds(self):
        start=self.ask("GET","/auth/start")
        self.assertEqual(start["status"],302)
        state=self.fake.last["state"]
        qs=("/auth/callback?code=some-secure-auth-code&state="+state
            +"&client_info=eyJ1aWQiOiJ0ZXN0IiwidXRpZCI6InRlc3QifQ")
        result=self.ask("GET",qs,headers={
            "Cookie":identity.COOKIE_STATE+"="+state})
        self.assertEqual(result["status"],302)
        self.assertEqual(result["location"],"/studio/")
        self.assertTrue(any(cookie.startswith(identity.COOKIE_SID+"=")
                            for cookie in result["cookies"]))

    def test_browser_callback_with_all_four_allowed_fields_succeeds(self):
        self.ask("GET","/auth/start")
        state=self.fake.last["state"]
        qs=("/auth/callback?code=some-secure-auth-code"
            +"&session_state=8a2b6c3d-1111-2222-3333-444455556666"
            +"&client_info=eyJ1aWQiOiJ0ZXN0IiwidXRpZCI6InRlc3QifQ"
            +"&state="+state)
        result=self.ask("GET",qs,headers={
            "Cookie":identity.COOKIE_STATE+"="+state})
        self.assertEqual(result["status"],302)

    def test_browser_callback_rejects_duplicate_client_info_without_consuming_flow(self):
        self.ask("GET","/auth/start")
        state=self.fake.last["state"]
        qs=("/auth/callback?code=some-secure-auth-code&state="+state
            +"&client_info=eyJ1aWQiOiJ0ZXN0In0&client_info=eyJ1aWQiOiJ0ZXN0In0")
        with redirect_stdout(io.StringIO()) as sink:
            result=self.ask("GET",qs,headers={
                "Cookie":identity.COOKIE_STATE+"="+state})
        self.assertEqual(result["status"],403)
        self.assertIn("duplicates=1",sink.getvalue())
        ok=self.ask("GET","/auth/callback?code=some-secure-auth-code&state="+state,
                    headers={"Cookie":identity.COOKIE_STATE+"="+state})
        self.assertEqual(ok["status"],302)

    def test_duplicate_state_is_rejected_without_consuming_flow(self):
        self.ask("GET","/auth/start")
        state=self.fake.last["state"]
        path="/auth/callback?code=some-secure-auth-code&state="+state+"&state="+state
        response=self.ask("GET",path,headers={"Cookie":identity.COOKIE_STATE+"="+state})
        self.assertEqual(response["status"],403)
        good=self.ask("GET","/auth/callback?code=some-secure-auth-code&state="+state,
                      headers={"Cookie":identity.COOKIE_STATE+"="+state})
        self.assertEqual(good["status"],302)

    def test_oauth_error_callback_logs_only_safe_param_names(self):
        self.ask("GET","/auth/start")
        state=self.fake.last["state"]
        callback=("/auth/callback?error=access_denied"
                  "&error_description=very-private-email-and-debug-details"
                  "&state="+state)
        sink=io.StringIO()
        with redirect_stdout(sink):
            result=self.ask("GET",callback,
                headers={"Cookie":identity.COOKIE_STATE+"="+state})
        self.assertEqual(result["status"],403)
        log=sink.getvalue()
        self.assertIn("STUDIO_AUTH_CALLBACK_DENIED invalid_callback",log)
        self.assertIn("param_names=error,error_description,state",log)
        self.assertNotIn("very-private-email-and-debug-details",log)
        self.assertNotIn(state,log)
        self.assertNotIn("access_denied",log)

    def test_many_callback_params_get_invalid_callback_not_internal_error(self):
        self.ask("GET","/auth/start")
        state=self.fake.last["state"]
        qs="state="+state+"&code=some-secure-auth-code"+"".join(
            "&unknown"+str(i)+"=private" for i in range(40))
        sink=io.StringIO()
        with redirect_stdout(sink):
            result=self.ask("GET","/auth/callback?"+qs,
                headers={"Cookie":identity.COOKIE_STATE+"="+state})
        self.assertEqual(result["status"],403)
        self.assertIn("invalid_callback",sink.getvalue())
        self.assertIn("param_names=too_many",sink.getvalue())
        self.assertNotIn("private",sink.getvalue())


    def test_complete_login_session_scoped_csrf_and_logout(self):
        sid,state=self.login()
        header={"Cookie":identity.COOKIE_SID+"="+sid}
        self.assertEqual(self.ask("GET","/auth/status",headers=header)["json"]["authenticated"],True)
        home=self.ask("GET","/",headers=header)
        self.assertEqual(home["status"],200)
        self.assertIn("Production Control",home["body"])
        self.assertNotIn("WELCOME BACK",home["body"])
        self.assertEqual(self.ask("GET","/login",headers=header)["location"],"/studio/")
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
        after=self.ask("GET","/",headers=header)
        self.assertEqual(after["status"],200)
        self.assertIn("欢迎回来，导演",after["body"])

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
