import base64
import tempfile
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from mobile_v06_core import (Rejected, challenge, decide, enroll, open_db,
                              pending, update_push)

SUBJECT = "microsoft-consumer-stable-sub-1234"
PAIR = "a" * 64
NOW = 1793750000.0

class MobileApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name + "/power.db"
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.der = self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.device = enroll(SUBJECT, PAIR, PAIR, base64.b64encode(self.der).decode(),
                             db_path=self.path, now=NOW)["device_id"]
        with open_db(self.path) as db:
            for suffix,action in [("start","start"),("stop","stop")]:
                db.execute("INSERT INTO requests(id,action,state,created,expires,updated)"
                           " VALUES(?,?,'pending',?,?,?)",
                           ("request-"+suffix+"-abcdefghijkl",action,NOW,NOW+300,NOW))

    def tearDown(self):
        self.tmp.cleanup()

    def start(self):
        return "request-start-abcdefghijkl"

    def stop(self):
        return "request-stop-abcdefghijkl"

    def make_signed(self, rid, decision="approve"):
        info = challenge(SUBJECT, self.device, rid, decision, self.path, now=NOW)
        payload = base64.b64decode(info["payload_b64"])
        signature = self.key.sign(payload, ec.ECDSA(hashes.SHA256()))
        return info,base64.b64encode(signature).decode()

    def decision(self, info, signature, **kwargs):
        return decide(SUBJECT,self.device,info["request_id"],info["nonce"],
                      signature,info["decision"],{"fake":"config"},self.path,
                      now=kwargs.pop("now",NOW+2),**kwargs)

    def test_approval_calls_provider_exactly_once(self):
        info,signature = self.make_signed(self.start())
        calls = []
        def plan(a,c):
            calls.append("plan-"+a)
            return {"allowed":True}
        def submit(a,c):
            calls.append("submit-"+a)
            return {"accepted":True}
        result = self.decision(info,signature,plan_fn=plan,submit_fn=submit)
        self.assertEqual(result["state"],"submitted")
        self.assertEqual(calls,["plan-start","submit-start"])
        with self.assertRaises(Rejected):
            self.decision(info,signature,plan_fn=plan,submit_fn=submit)
        self.assertEqual(calls,["plan-start","submit-start"])

    def test_deny_does_not_touch_provider(self):
        info,sig = self.make_signed(self.stop(),"deny")
        def never(*_):
            raise AssertionError("Cloud API must not run on deny")
        self.assertEqual(self.decision(info,sig,plan_fn=never,submit_fn=never)["state"],"denied")
        self.assertEqual(pending(SUBJECT,self.device,self.path,now=NOW+3)["requests"][0]["action"],"start")

    def test_signature_must_match_action_and_decision(self):
        info,sig = self.make_signed(self.start(),"approve")
        info["decision"] = "deny"
        with self.assertRaises(Rejected):
            self.decision(info,sig)
        info["decision"] = "approve"
        key2 = ec.generate_private_key(ec.SECP256R1())
        bad = base64.b64encode(key2.sign(
            base64.b64decode(info["payload_b64"]),ec.ECDSA(hashes.SHA256()))).decode()
        with self.assertRaises(Rejected):
            self.decision(info,bad)

    def test_expired_challenge_rejected(self):
        info,sig = self.make_signed(self.start())
        with self.assertRaises(Rejected):
            self.decision(info,sig,now=NOW+91,plan_fn=lambda *_:{"allowed":True})

    def test_preflight_blocked_never_submits(self):
        info,sig=self.make_signed(self.stop())
        out=self.decision(info,sig,plan_fn=lambda *_:{"allowed":False,
                          "reason":"comfyui_queue_not_verified"},
                          submit_fn=lambda *_:self.fail("no submit"))
        self.assertEqual(out["state"],"blocked")

    def test_pairing_once_only_and_wrong_user_denied(self):
        with self.assertRaises(Rejected):
            enroll(SUBJECT,PAIR,PAIR,base64.b64encode(self.der).decode(),
                   db_path=self.path)
        with self.assertRaises(Rejected):
            pending("other-owner-sub-unknown",self.device,self.path,now=NOW)
        with self.assertRaises(Rejected):
            pending(SUBJECT,"wrong-device",self.path,now=NOW)

    def test_bad_pairing_cannot_enroll(self):
        with self.assertRaises(Rejected):
            enroll(SUBJECT,"bad","expected-secret-with-32-plus-characters",
                   base64.b64encode(self.der).decode(),db_path=self.tmp.name+"/other.db")

    def test_fcm_update_cannot_rebind_device(self):
        with self.assertRaises(Rejected):
            update_push(SUBJECT,"another-device","my-token",self.path)
        self.assertTrue(update_push(SUBJECT,self.device,"my-token",self.path)["ok"])

    def test_challenge_is_single_active_and_invalidates_old(self):
        first,sig=self.make_signed(self.start())
        second=challenge(SUBJECT,self.device,self.start(),"approve",self.path,now=NOW+1)
        self.assertNotEqual(first["nonce"],second["nonce"])
        with self.assertRaises(Rejected):
            self.decision(first,sig)

if __name__=="__main__":
    unittest.main()
