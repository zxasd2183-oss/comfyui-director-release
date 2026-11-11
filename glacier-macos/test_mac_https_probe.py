"""Mac app HTTPS probe must ship a trusted CA bundle and fail closed."""
import pathlib
import ssl
import unittest
from unittest.mock import patch

import certifi
from mac_https_probe import create_tls_context, socks_failure_message
from mac_ui08 import MacGlacierUI08
from ui08 import GlacierUI08


class MacTlsTests(unittest.TestCase):
    def test_root_bundle_is_packaged(self):
        bundle=pathlib.Path(certifi.where())
        self.assertTrue(bundle.is_file())
        self.assertGreater(bundle.stat().st_size,100_000)
        ctx=create_tls_context()
        self.assertEqual(ctx.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertGreater(ctx.cert_store_stats().get("x509_ca",0),80)

    def test_missing_bundle_fails_closed(self):
        with patch("mac_https_probe.certifi.where",return_value="/missing-ca-bundle.pem"):
            with self.assertRaises(RuntimeError):
                create_tls_context()

    def test_socks_connect_result_reports_precise_failure(self):
        self.assertIsNone(socks_failure_message(bytes((5, 0, 0, 1))))
        for code in range(1, 9):
            msg = socks_failure_message(bytes((5, code, 0, 1)))
            self.assertIn(f"SOCKS5 代码 {code}", msg)
        self.assertIn("无效响应", socks_failure_message(b"bad"))

    def test_mac_uses_dedicated_probe_mixin(self):
        self.assertTrue(issubclass(MacGlacierUI08,GlacierUI08))
        self.assertIsNot(MacGlacierUI08.start_connection_check,
                         GlacierUI08.start_connection_check)


if __name__=="__main__":
    unittest.main()
