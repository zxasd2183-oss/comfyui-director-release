import base64
import hmac
import hashlib
import os
import re
import stat
import struct
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, unquote

from enroll_totp import build_totp_uri, load_seed, verify_locally


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "seed"
        self.seed = base64.b32encode(b"12345678901234567890").decode("ascii")
        self.file.write_text(self.seed + "\n", encoding="ascii")
        self.file.chmod(0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        return load_seed(str(self.file), required_uid=os.getuid())

    def test_root_owned_private_seed_can_be_loaded(self):
        self.assertEqual(self.read(), self.seed)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)

    def test_unsafe_permissions_are_rejected(self):
        self.file.chmod(0o644)
        with self.assertRaises(RuntimeError):
            self.read()

    def test_symlink_is_rejected(self):
        link = Path(self.tmp.name) / "link"
        link.symlink_to(self.file)
        with self.assertRaises(RuntimeError):
            load_seed(str(link), required_uid=os.getuid())

    def test_uri_is_standard_totp(self):
        uri = build_totp_uri(self.seed)
        parsed = urlsplit(uri)
        self.assertEqual(parsed.scheme, "otpauth")
        self.assertEqual(parsed.netloc, "totp")
        self.assertEqual(unquote(parsed.path), "/Director VPS:GPU")
        query = parse_qs(parsed.query)
        self.assertEqual(query["secret"], [self.seed])
        self.assertEqual(query["digits"], ["6"])
        self.assertEqual(query["period"], ["30"])

    def test_code_is_verified_without_gpu_side_effect(self):
        now = 1_790_000_000.0
        secret_bytes = base64.b32decode(self.seed)
        step = int(now // 30)
        digest = hmac.new(secret_bytes, struct.pack(">Q", step), hashlib.sha1).digest()
        offset = digest[-1] & 0x0f
        code = ((struct.unpack(">I", digest[offset:offset+4])[0] & 0x7fffffff)
                % 1000000)
        self.assertTrue(verify_locally(self.seed, f"{code:06d}", now=now))
        self.assertFalse(verify_locally(self.seed, "not-an-otp", now=now))


if __name__ == "__main__":
    unittest.main()
