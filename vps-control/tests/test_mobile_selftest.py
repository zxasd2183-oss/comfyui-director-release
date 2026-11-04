"""Offline integration/security tests for biometric *non-power* self-test.

No Microsoft network access, GPU credentials, cloud provider requests,
device pairing codes, or GPU power state changes.
"""
import base64
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from mobile_v06_api import AuthRejected, build_handler
from mobile_v06_core import Rejected, enroll, open_db
from mobile_v06_selftest import canonical, start, verify, TTL_SECONDS


SUBJECT = "microsoft-account-test-sub-1234567890"
PAIR = "LOCAL_TEST_SECRET_" + "p" * 40


class Identity:
    def verify(self, token):
        if token == "valid-test-identity":
            return SUBJECT
        if token == "other-test-identity":
            return "other-microsoft-account-99999999"
        raise AuthRejected("microsoft_auth_invalid")


class BiometricSelftestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = self.tmp.name + "/power.db"
        self.signer = ec.generate_private_key(ec.SECP256R1())
        pub = self.signer.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self.provider_calls = 0
        def forbidden_provider():
            self.provider_calls += 1
            raise AssertionError("NON-POWER selftest must never touch GPU credentials")
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), build_handler(Identity(), forbidden_provider, PAIR, self.db)
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.root = "http://127.0.0.1:" + str(self.server.server_port)
        with open_db(self.db) as db:
            # Existing production request table must be unaffected.
            db.execute(
                "INSERT INTO requests(id,action,state,created,expires,updated)"
                " VALUES('TEST-POWER-REQUEST-001','start','pending',1000,9999999999,1000)"
            )
        record = enroll(
            SUBJECT, PAIR, PAIR, base64.b64encode(pub).decode("ascii"),
            db_path=self.db
        )
        self.device = record["device_id"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def post(self, operation, payload, bearer="valid-test-identity"):
        headers = {"Content-Type": "application/json"}
        if bearer is not None:
            headers["Authorization"] = "Bearer " + bearer
        request = Request(
            self.root + "/api/v1/mobile/" + operation,
            data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        try:
            with urlopen(request, timeout=6) as response:
                return response.status, json.load(response)
        except HTTPError as failure:
            with failure:
                return failure.code, json.load(failure)

    def good_signature(self, challenge):
        data = base64.b64decode(challenge["payload_b64"])
        return base64.b64encode(
            self.signer.sign(data, ec.ECDSA(hashes.SHA256()))
        ).decode("ascii")

    def assert_requests_unchanged(self):
        with open_db(self.db) as db:
            req = db.execute(
                "SELECT action,state,expires FROM requests "
                "WHERE id='TEST-POWER-REQUEST-001'"
            ).fetchone()
            self.assertEqual((req["action"], req["state"], req["expires"]),
                             ("start", "pending", 9999999999))
            count = db.execute("SELECT count(*) FROM mobile_challenge").fetchone()[0]
            self.assertEqual(count, 0)
        self.assertEqual(self.provider_calls, 0)

    def test_anonymous_and_bad_microsoft_identity_are_rejected(self):
        for endpoint in ("selftest_challenge", "selftest_verify"):
            code, body = self.post(endpoint, {"device_id": self.device}, bearer=None)
            self.assertEqual((code, body["reason"]), (401, "microsoft_login_required"))
            code, body = self.post(endpoint, {"device_id": self.device}, bearer="wrong")
            self.assertEqual((code, body["reason"]), (401, "microsoft_auth_invalid"))
        self.assert_requests_unchanged()

    def test_requires_correct_enrolled_device_and_owner(self):
        for bearer, device, expected in (
            ("valid-test-identity", "wrong-device-id", "wrong_device"),
            ("other-test-identity", self.device, "device_not_enrolled"),
        ):
            code, response = self.post(
                "selftest_challenge", {"device_id": device}, bearer=bearer
            )
            self.assertEqual((code, response["reason"]), (409, expected))
        self.assert_requests_unchanged()

    def test_real_p256_signature_validated_and_replay_rejected(self):
        code, challenge = self.post("selftest_challenge", {"device_id": self.device})
        self.assertEqual(code, 200)
        self.assertEqual(challenge["kind"], "biometric_selftest")
        payload = base64.b64decode(challenge["payload_b64"])
        self.assertEqual(payload, canonical(self.device, challenge["nonce"],
                                            challenge["expires_at"]))
        signed = self.good_signature(challenge)
        params = {"device_id": self.device, "nonce": challenge["nonce"],
                  "signature": signed}
        code, verified = self.post("selftest_verify", params)
        self.assertEqual(code, 200)
        self.assertTrue(verified["signature_verified"])
        self.assertTrue(verified["one_time_challenge_consumed"])
        self.assertFalse(verified["gpu_operation_performed"])
        code, replay = self.post("selftest_verify", params)
        self.assertEqual((code, replay["reason"]), (409, "selftest_expired_or_consumed"))
        self.assert_requests_unchanged()

    def test_invalid_signature_consumes_challenge(self):
        code, challenge = self.post("selftest_challenge", {"device_id": self.device})
        self.assertEqual(code, 200)
        attacker = ec.generate_private_key(ec.SECP256R1())
        wrong = base64.b64encode(attacker.sign(
            base64.b64decode(challenge["payload_b64"]), ec.ECDSA(hashes.SHA256())
        )).decode("ascii")
        params = {"device_id": self.device, "nonce": challenge["nonce"],
                  "signature": wrong}
        code, body = self.post("selftest_verify", params)
        self.assertEqual((code, body["reason"]), (409, "selftest_signature_invalid"))
        params["signature"] = self.good_signature(challenge)
        code, body = self.post("selftest_verify", params)
        self.assertEqual((code, body["reason"]), (409, "selftest_expired_or_consumed"))
        self.assert_requests_unchanged()

    def test_wrong_nonce_cannot_consume_valid_challenge(self):
        code, challenge = self.post("selftest_challenge", {"device_id": self.device})
        signed = self.good_signature(challenge)
        code, response = self.post("selftest_verify", {
            "device_id": self.device, "nonce": "a" * 32, "signature": signed
        })
        self.assertEqual((code, response["reason"]), (409, "selftest_expired_or_consumed"))
        code, response = self.post("selftest_verify", {
            "device_id": self.device, "nonce": challenge["nonce"], "signature": signed
        })
        self.assertEqual(code, 200)
        self.assert_requests_unchanged()

    def test_expiry_and_new_challenge_invalidate_old_proofs(self):
        first = start(SUBJECT, self.device, db_path=self.db, now=1000)
        assert first["expires_at"] == 1000 + TTL_SECONDS
        with self.assertRaisesRegex(Rejected, "selftest_expired_or_consumed"):
            verify(SUBJECT, self.device, first["nonce"],
                   self.good_signature(first), db_path=self.db, now=1091)
        # A fresh challenge makes the old one unusable even before expiry.
        a = start(SUBJECT, self.device, db_path=self.db, now=5000)
        b = start(SUBJECT, self.device, db_path=self.db, now=5001)
        with self.assertRaisesRegex(Rejected, "selftest_expired_or_consumed"):
            verify(SUBJECT, self.device, a["nonce"],
                   self.good_signature(a), db_path=self.db, now=5002)
        ok = verify(SUBJECT, self.device, b["nonce"],
                    self.good_signature(b), db_path=self.db, now=5002)
        self.assertTrue(ok["signature_verified"])
        self.assert_requests_unchanged()

    def test_concurrent_replay_only_one_signature_succeeds(self):
        code, challenge = self.post("selftest_challenge", {"device_id": self.device})
        self.assertEqual(code, 200)
        params = {"device_id": self.device, "nonce": challenge["nonce"],
                  "signature": self.good_signature(challenge)}
        barrier = threading.Barrier(2)
        def worker():
            barrier.wait(timeout=5)
            return self.post("selftest_verify", params)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(sorted(r[0] for r in results), [200, 409])
        self.assert_requests_unchanged()

    def test_selftest_does_not_allow_gpu_fields_or_cross_domain_signature(self):
        code, challenge = self.post("selftest_challenge", {
            "device_id": self.device, "action": "start", "decision": "approve",
            "request_id": "TEST-POWER-REQUEST-001"
        })
        self.assertEqual(code, 200)
        canonical_bytes = base64.b64decode(challenge["payload_b64"])
        self.assertTrue(canonical_bytes.startswith(b"JIPITE-SELFTEST-V1\n"))
        self.assertNotIn(b"TEST-POWER-REQUEST-001", canonical_bytes)
        signed = self.good_signature(challenge)
        code, result = self.post("selftest_verify", {
            "device_id": self.device, "nonce": challenge["nonce"],
            "signature": signed, "action": "start", "decision": "approve"
        })
        self.assertEqual(code, 200)
        self.assertFalse(result["gpu_operation_performed"])
        self.assert_requests_unchanged()


if __name__ == "__main__":
    unittest.main()
