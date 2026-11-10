"""Core diagnostics may reveal only canned categories, never VLESS credentials."""
import io
import time
import unittest
from mac_proxy_diagnostics import classify, start_capture, latest_hint, reset_hints


class _FakeProcess:
    def __init__(self,lines):
        self.stdout=io.BytesIO(lines.encode('utf-8'))


class MacCoreDiagnosticsTests(unittest.TestCase):
    def test_no_raw_details_ever_returned(self):
        secret="vless://11111111-1111-1111-1111-111111111111@secret.example:443?pbk=SECRET"
        for error,expected in (
            ("reality verification failed", "REALITY 握手验证失败"),
            ("dial tcp: lookup node.example: no such host", "节点域名解析失败"),
            ("tls: failed to verify certificate", "TLS 证书校验失败"),
            ("websocket: bad handshake", "WebSocket 握手失败"),
            ("i/o timeout", "节点连接或握手超时"),
        ):
            hint=classify("ERROR "+error+" "+secret)
            self.assertEqual(hint,expected)
            self.assertNotIn("secret.example",hint)
            self.assertNotIn("11111111",hint)
        self.assertIsNone(classify(secret))
        self.assertIsNone(classify("INFO network connection accepted"))

    def test_stdout_reader_stores_only_category_and_never_full_line(self):
        proc=_FakeProcess("ERROR outbound: reality verification failed for vless://SECRET@node.example:443\n")
        start_capture(proc)
        for _ in range(30):
            hint=latest_hint(proc)
            if hint:
                break
            time.sleep(0.01)
        self.assertEqual(hint,"REALITY 握手验证失败")
        self.assertNotIn("SECRET",hint)
        reset_hints(proc)
        self.assertIsNone(latest_hint(proc))

    def test_core_stdout_concealed_unknown_outbound_failure(self):
        proc=_FakeProcess("2026 ERROR outbound/vless[node]: unrecognized issue on secret.example\n")
        start_capture(proc)
        hint=None
        for _ in range(30):
            hint=latest_hint(proc)
            if hint:
                break
            time.sleep(0.01)
        self.assertEqual(hint,"VLESS 出站连接失败，具体原因待进一步确认")
        self.assertNotIn("secret.example",hint)


if __name__=="__main__":
    unittest.main()
