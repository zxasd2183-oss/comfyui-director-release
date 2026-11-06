"""Private persistent Microsoft owner sessions, restart and security regression tests."""
import hashlib
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import session_store as store
import studio_identity as identity

CFG={"client_id":"12345678-1234-1234-1234-123456789abc",
     "client_secret":"unit-test-only-long-confidential-secret",
     "owner_sub":"unit-test-owner-subject"}


class FakeMSAL:
    def __init__(self):self.last=None;self.count=0
    def initiate_auth_code_flow(self,scopes,redirect_uri,response_mode,max_age):
        self.count+=1
        self.last={"state":"st"+str(self.count).zfill(20),
                   "nonce":"example-fake-nonce-long-enough-123456",
                   "code_verifier":"v"*50,
                   "auth_uri":identity.AUTHORITY+"/oauth2/v2.0/authorize?test=1"}
        return dict(self.last)
    def acquire_token_by_auth_code_flow(self,flow,query):
        return {"id_token":"fake-token-never-stored"}


class PersistentIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/"studio_owner_sessions.sqlite"
        self.now=[1000]
        self.app=FakeMSAL()

    def service(self,config=CFG):
        def verified(_):
            return {"tid":identity.PERSONAL_TID,"iss":identity.ISSUER,
                    "aud":config["client_id"],"sub":config["owner_sub"],
                    "nonce":hashlib.sha256(self.app.last["nonce"].encode()).hexdigest()}
        return identity.MicrosoftStudioIdentity(
            config,msal_app=self.app,validator=verified,clock=lambda:self.now[0],
            session_db_path=self.db)

    def login(self,service):
        _,state=service.start()
        return service.finish({"state":state,"code":"some-secure-auth-code"},state)

    def test_survives_server_restart_and_old_expiry_limits(self):
        service=self.service()
        sid=self.login(service)
        first_csrf=service.check(sid)["csrf"]
        self.assertEqual(stat.S_IMODE(self.db.stat().st_mode),0o600)
        self.assertIn("Max-Age=2592000",identity.session_cookie(sid))
        self.assertIn("Secure; HttpOnly; SameSite=Lax",identity.session_cookie(sid))
        self.now[0]+=7201  # formerly lost after 2 hours
        restarted=self.service()
        self.assertEqual(restarted.check(sid)["csrf"],first_csrf)
        self.now[0]+=1801  # formerly lost after 30 idle minutes
        self.assertIsNotNone(restarted.check(sid))
        self.now[0]+=identity.SESSION_TTL
        self.assertIsNone(self.service().check(sid))

    def test_session_handles_and_owner_subject_are_not_persisted_raw(self):
        service=self.service()
        sid=self.login(service)
        contents=self.db.read_bytes()
        self.assertNotIn(sid.encode(),contents)
        self.assertNotIn(CFG["owner_sub"].encode(),contents)
        self.assertNotIn(b"fake-token-never-stored",contents)
        self.assertIn(hashlib.sha256(sid.encode()).hexdigest().encode(),contents)

    def test_explicit_logout_revokes_after_restart(self):
        service=self.service()
        sid=self.login(service)
        self.assertIsNotNone(self.service().check(sid))
        service.logout(sid)
        self.assertIsNone(self.service().check(sid))

    def test_inactivity_expiry_and_original_absolute_expiry(self):
        service=self.service()
        sid=self.login(service)
        self.now[0]+=identity.SESSION_IDLE+1
        self.assertIsNone(self.service().check(sid))
        sid=self.login(service)
        for n in range(3):
            self.now[0]+=identity.SESSION_IDLE//4
            self.assertIsNotNone(self.service().check(sid))
        self.now[0]+=identity.SESSION_TTL
        self.assertIsNone(self.service().check(sid))

    def test_invalid_owner_binding_denies_previous_session(self):
        service=self.service()
        sid=self.login(service)
        other={**CFG,"owner_sub":"other-owner-subject"}
        self.assertIsNone(self.service(config=other).check(sid))
        self.assertIsNone(self.service().check(sid))

    def test_persistent_limit_does_not_revoke_existing_owner_sessions(self):
        service=self.service()
        for i in range(identity.MAX_SESSIONS):
            self.login(service)
        with self.assertRaisesRegex(identity.IdentityError,"too_many_sessions"):
            self.login(service)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM studio_owner_sessions"
                                        ).fetchone()[0],identity.MAX_SESSIONS)

    def test_unsafe_symlink_and_permissions_fail_closed(self):
        service=self.service()
        sid=self.login(service)
        self.db.chmod(0o644)
        self.assertIsNone(service.check(sid))
        with self.assertRaises(store.SessionStoreError):
            store.PersistentSessions(self.db)
        self.db.chmod(0o600)
        replacement=Path(self.tmp.name)/"replace.sqlite"
        self.db.rename(replacement)
        self.db.symlink_to(replacement)
        with self.assertRaises(store.SessionStoreError):
            store.PersistentSessions(self.db)

    def test_unavailable_storage_never_downgrades_to_memory_sessions(self):
        service=self.service()
        sid=self.login(service)
        self.db.unlink()
        self.db.mkdir()
        self.assertIsNone(service.check(sid))
        # A valid Microsoft login must still fail closed rather than enter a
        # purely in-memory or unsigned fallback.
        with self.assertRaisesRegex(identity.IdentityError,
                                     "identity_session_storage_unavailable"):
            self.login(service)


if __name__=="__main__":
    unittest.main()
