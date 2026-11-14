"""Human-approved RDP screen share: short one-time code, session-life token.

Neither the Worker nor MCP exposes mouse/keyboard, arbitrary commands or a
long-lived credential to a chat. The RDP companion revokes on Stop/session end.
"""
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent

VALID_SESSION = "e" * 32
PAIRED = ("application/json", json.dumps({
    "ok": True, "sharing": True, "session_token": VALID_SESSION,
}).encode("ascii"))


class DesktopBridgeTests(unittest.TestCase):
    def tearDown(self):
        agent.unpair_desktop()

    def pair(self, code="a" * 32):
        with patch.object(agent, "_desktop_http", return_value=PAIRED) as remote:
            result = agent.pair_desktop(code)
        self.assertTrue(result["ok"])
        self.assertFalse(result["control_enabled"])
        self.assertNotIn("session_token", result)
        self.assertNotIn("code", result)
        remote.assert_called_once_with("/v1/pair", code, pairing=True)
        return result

    def test_unpaired_cannot_capture_and_never_calls_companion(self):
        agent.unpair_desktop()
        with patch.object(agent, "_desktop_http") as remote:
            with self.assertRaisesRegex(ValueError, "desktop_not_paired"):
                agent.desktop_frame()
            remote.assert_not_called()

    def test_live_local_consent_and_distinct_private_session_required(self):
        code = "a" * 32
        for item in (
            {"ok": True, "sharing": False, "session_token": VALID_SESSION},
            {"ok": True, "sharing": True, "session_token": code.upper()},
            {"ok": True, "sharing": True},
        ):
            with patch.object(agent, "_desktop_http", return_value=(
                    "application/json", json.dumps(item).encode("ascii"))):
                self.assertFalse(agent.pair_desktop(code)["ok"])
        self.assertFalse(agent.desktop_status()["paired"])
        self.pair(code)
        self.assertEqual(agent._desktop_session_token(), VALID_SESSION)

    def test_session_has_no_wall_clock_expiration(self):
        self.pair()
        with patch.object(agent.time, "monotonic", return_value=9e12):
            with patch.object(agent, "_desktop_http", return_value=(
                    "application/json", b'{"ok":true,"sharing":true}')) as remote:
                self.assertTrue(agent.desktop_status()["sharing"])
            remote.assert_called_once_with("/v1/status", VALID_SESSION)
        # Only explicit unpair or an inactive companion invalidates access.
        agent.unpair_desktop()
        with self.assertRaisesRegex(ValueError, "desktop_not_paired"):
            agent.desktop_frame()

    def test_lock_disconnect_or_stop_revokes_cached_pairing(self):
        self.pair()
        with patch.object(agent, "_desktop_http", return_value=(
                "application/json", b'{"ok":true,"sharing":false}')):
            state = agent.desktop_status()
        self.assertFalse(state["paired"])
        self.assertFalse(state["sharing"])
        self.assertIsNone(agent._desktop_session_token())

    def test_snapshot_needs_jpeg_and_does_not_expose_controls(self):
        self.pair()
        jpg = bytes((255, 216)) + b"f" * 256 + bytes((255, 217))
        with patch.object(agent, "_desktop_http", return_value=("image/jpeg", jpg)):
            data, digest = agent.desktop_frame()
        self.assertEqual(data, jpg)
        self.assertEqual(len(digest), 64)
        with patch.object(agent, "_desktop_http", return_value=(
                "image/jpeg", b"not a screenshot" * 50)):
            with self.assertRaisesRegex(ValueError, "desktop_frame_unavailable"):
                agent.desktop_frame()
        self.assertFalse(agent.capabilities()["supports_desktop_keyboard_or_mouse"])
        self.assertTrue(agent.capabilities()["supports_desktop_view_only"])

    def test_http_pair_requires_worker_bearer_and_valid_code(self):
        server = agent.ThreadingHTTPServer(("127.0.0.1", 0), agent.Handler)
        server.token = "d" * 64
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            uri = f"http://127.0.0.1:{server.server_port}/v14/desktop/pair"

            def call(headers, body):
                request = urllib.request.Request(
                    uri, method="POST", headers=headers,
                    data=json.dumps(body).encode("utf-8"))
                try:
                    with urllib.request.urlopen(request, timeout=3) as answer:
                        return answer.status, json.load(answer)
                except urllib.error.HTTPError as err:
                    return err.code, json.loads(err.read())

            result, data = call({}, {"code": "a" * 32})
            self.assertEqual(result, 401)
            self.assertEqual(data["reason"], "unauthorized")
            headers = {"Authorization": "Bearer " + "d" * 64}
            result, data = call(headers, {"code": "NOT_A_PAIR_CODE"})
            self.assertEqual(result, 409)
            self.assertEqual(data["reason"], "desktop_pair_code_invalid")
            with patch.object(agent, "_desktop_http", return_value=PAIRED):
                result, data = call(headers, {"code": "a" * 32})
            self.assertEqual(result, 200)
            self.assertTrue(data["paired"])
            self.assertNotIn("session_token", data)
            self.assertNotIn("code", data)
            self.assertNotIn("seconds_remaining_max", data)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_companion_protocol_stays_loopback_and_read_only(self):
        script = (Path(__file__).resolve().parents[1] /
                  "DirectorDesktopShare.ps1").read_text(encoding="utf-8")
        self.assertIn("TcpListener]::new([System.Net.IPAddress]::Loopback", script)
        self.assertIn("POST /v1/pair", script)
        self.assertIn("X-Director-Desktop-Session", script)
        self.assertIn("WTSRegisterSessionNotification", script)
        self.assertIn("reason == 4 || reason == 6 || reason == 7", script)
        self.assertIn("Stop Immediately", script)
        self.assertNotIn("mouse_event", script)
        self.assertNotIn("keybd_event", script)


if __name__ == "__main__":
    unittest.main()
