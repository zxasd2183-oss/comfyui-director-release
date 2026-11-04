"""Offline HTTP integration tests for the Jipite mobile approval API.

This file never calls a GPU power provider, connects to Microsoft, or binds
a public port. A fake identity validates local request boundaries.
"""
import base64
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from mobile_v06_api import AuthRejected, build_handler
from mobile_v06_core import open_db

SUBJECT = "microsoft-consumer-local-test-12345"
PAIR = "LOCAL_TEST_PAIR_" + "x" * 50
REQUEST_ID = "request-stop-v07-api-abcdefghijkl"


class TestIdentity:
    def verify(self, bearer):
        if bearer != "local-test-token":
            raise AuthRejected("microsoft_auth_invalid")
        return SUBJECT


class MobileHttpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = self.temp.name + "/requests.db"
        with open_db(self.db_path) as db:
            db.execute(
                "INSERT INTO requests(id,action,state,created,expires,updated) "
                "VALUES(?,?,'pending',strftime('%s','now'),strftime('%s','now')+300,strftime('%s','now'))",
                (REQUEST_ID, "stop")
            )
        def config_must_not_run():
            raise AssertionError("GPU provider configuration must not load on deny")
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            build_handler(TestIdentity(), config_must_not_run, PAIR, self.db_path)
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def post(self, op, payload, token=None):
        data = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        req = Request(self.base + "/api/v1/mobile/" + op, data=data,
                      headers=headers, method="POST")
        try:
            with urlopen(req, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_anonymous_probe_proves_auth_is_required(self):
        status, data = self.post("pending", {})
        self.assertEqual(status, 401)
        self.assertEqual(data["reason"], "microsoft_login_required")

    def test_invalid_bearer_is_not_a_login(self):
        status, data = self.post("pending", {}, "invalid")
        self.assertEqual(status, 401)
        self.assertEqual(data["reason"], "microsoft_auth_invalid")

    def test_malformed_payload_is_rejected_before_identity(self):
        request = Request(
            self.base + "/api/v1/mobile/pending",
            data=b"[]",
            headers={"Content-Type": "application/json", "Authorization": "Bearer local-test-token"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as response:
            urlopen(request, timeout=5)
        self.assertEqual(response.exception.code, 400)

    def test_enroll_then_biometric_style_deny_without_gpu(self):
        key = ec.generate_private_key(ec.SECP256R1())
        public = key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        code, data = self.post(
            "enroll",
            {"pairing_code": PAIR, "public_key": base64.b64encode(public).decode(),
             "fcm_token": ""},
            token="local-test-token"
        )
        self.assertEqual(code, 200)
        device = data["device_id"]

        code, data = self.post("pending", {"device_id": device}, "local-test-token")
        self.assertEqual(code, 200)
        self.assertEqual(data["requests"][0]["action"], "stop")

        code, challenge = self.post(
            "challenge", {"device_id": device, "request_id": REQUEST_ID, "decision": "deny"},
            "local-test-token"
        )
        self.assertEqual(code, 200)
        signed = base64.b64encode(key.sign(
            base64.b64decode(challenge["payload_b64"]), ec.ECDSA(hashes.SHA256())
        )).decode()
        response = {"device_id": device, "request_id": REQUEST_ID,
                    "nonce": challenge["nonce"], "signature": signed, "decision": "deny"}

        # No cloud provider or GPU config is used on denial.
        code, data = self.post("decision", response, "local-test-token")
        self.assertEqual(code, 200)
        self.assertEqual(data["state"], "denied")
        code, data = self.post("decision", response, "local-test-token")
        self.assertEqual(code, 409)
        self.assertEqual(data["reason"], "challenge_expired_or_consumed")

    def test_wrong_device_does_not_fetch_pending(self):
        status, data = self.post("pending", {"device_id": "not-enrolled"}, "local-test-token")
        self.assertEqual(status, 409)
        self.assertEqual(data["reason"], "device_not_enrolled")


if __name__ == "__main__":
    unittest.main()
