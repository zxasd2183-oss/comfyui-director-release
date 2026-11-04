import json
import unittest
from io import BytesIO
from urllib.parse import parse_qs

from mobile_v06_core import Rejected, validate_push_token
from mobile_v06_api import push_dispatcher
from mobile_v06_xiaomi import URL, send_xiaomi


class Response:
    def __init__(self, data):
        self.data = json.dumps(data).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self, count):
        return self.data[:count]


class XiaomiPushTests(unittest.TestCase):
    REQUEST = "test-request-1234567890abcde"

    def test_mainland_rest_contract_no_power_authority(self):
        calls = []
        def transport(req, timeout):
            calls.append((req, timeout))
            return Response({"result": "ok", "code": 0})
        send_xiaomi("abcdefgh1234567890", self.REQUEST, "start", "secret-ABCDEFG", 50000, transport)
        self.assertEqual(len(calls), 1)
        req, timeout = calls[0]
        self.assertEqual(req.full_url, URL)
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Authorization"), "key=secret-ABCDEFG")
        body = parse_qs(req.data.decode())
        self.assertEqual(body["registration_id"], ["abcdefgh1234567890"])
        self.assertEqual(body["restricted_package_name"], ["cn.borealos.jipite"])
        self.assertEqual(body["time_to_live"], ["50000"])
        payload = json.loads(body["payload"][0])
        self.assertEqual(payload["kind"], "gpu-approval")
        self.assertEqual(payload["action"], "start")
        self.assertEqual(payload["request_id"], self.REQUEST)
        self.assertNotIn("approve", payload)
        self.assertNotIn("signature", payload)

    def test_ttl_caps_at_request_five_minutes(self):
        body = []
        def transport(req, timeout):
            body.append(parse_qs(req.data.decode()))
            return Response({"result": "ok", "code": 0})
        send_xiaomi("abcdefgh1234567890", self.REQUEST, "stop", "secret-ABCDEFG", 999999, transport)
        self.assertEqual(body[0]["time_to_live"], ["300000"])

    def test_provider_rejection_is_not_delivery(self):
        with self.assertRaises(RuntimeError):
            send_xiaomi("abcdefgh1234567890", self.REQUEST, "start",
                        "secret-ABCDEFG", transport=lambda req,timeout:Response(
                            {"result":"error","code":65015}))

    def test_invalid_regid_rejected_without_http(self):
        with self.assertRaises(ValueError):
            send_xiaomi("abc;/", self.REQUEST, "start", "secret-ABCDEFG",
                        transport=lambda *_:self.fail("HTTP must not run"))

    def test_token_prefix_and_dispatch(self):
        calls = []
        send = push_dispatcher(
            lambda *args: calls.append(("fcm",)+args),
            lambda *args: calls.append(("xiaomi",)+args))
        send("xm:abcdefgh1234567890", self.REQUEST, "stop", 9000)
        send("fcm_token", self.REQUEST, "start", 9000)
        self.assertEqual(calls[0][0], "xiaomi")
        self.assertEqual(calls[0][1], "abcdefgh1234567890")
        self.assertEqual(calls[1][0], "fcm")
        with self.assertRaises(Rejected):
            validate_push_token("xm:bad;evil")
        validate_push_token("xm:abcdefgh1234567890")


if __name__ == "__main__":
    unittest.main()
