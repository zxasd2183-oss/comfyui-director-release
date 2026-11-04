import http.server
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from power_approval_http import build_handler


class ApprovalWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = "a" * 64
        cls.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            build_handler(cls.key, "A" * 32, "/nonexistent/config",
                          "/nonexistent/db"))
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_public_root_not_found(self):
        with self.assertRaises(HTTPError) as err:
            urlopen(self.url + "/", timeout=5)
        self.assertEqual(err.exception.code, 404)

    def test_wrong_secret_path_not_found(self):
        with self.assertRaises(HTTPError) as err:
            urlopen(self.url + "/approve/guess", timeout=5)
        self.assertEqual(err.exception.code, 404)

    def test_valid_secret_route_does_not_show_any_otp_seed(self):
        with urlopen(self.url + "/approve/" + self.key, timeout=5) as resp:
            page = resp.read().decode("utf-8")
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers["Cache-Control"], "no-store")
            self.assertEqual(resp.headers["Referrer-Policy"], "no-referrer")
            self.assertIn("输入 ChatGPT", page)
            self.assertNotIn("A" * 32, page)

    def test_post_requires_risk_acknowledgement(self):
        request = Request(
            self.url + "/approve/" + self.key,
            data=b"id=test&otp=123456&phrase=START+GPU",
            headers={"Content-Type":"application/x-www-form-urlencoded"})
        with self.assertRaises(HTTPError) as err:
            urlopen(request, timeout=5)
        self.assertEqual(err.exception.code, 400)

    def test_path_with_query_is_rejected_for_post(self):
        request = Request(
            self.url + "/approve/" + self.key + "?bypass=1",
            data=b"ack=yes&id=test&otp=123456&phrase=START+GPU",
            headers={"Content-Type":"application/x-www-form-urlencoded"})
        with self.assertRaises(HTTPError) as err:
            urlopen(request, timeout=5)
        self.assertEqual(err.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
