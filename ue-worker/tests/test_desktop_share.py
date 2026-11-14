"""Human-approved RDP screen + locally armed narrow input protocol.

The Worker exposes only allowlisted click/key/text actions. Owner must locally
arm input; no arbitrary commands or long-lived credential reaches ChatGPT.
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
        self.assertTrue(agent.capabilities()["supports_desktop_keyboard_or_mouse"])
        self.assertTrue(agent.capabilities()["supports_desktop_view_only"])

    def test_input_invalid_or_not_locally_armed_never_reaches_companion(self):
        self.pair()
        actions = [
            {}, {"action": "click", "x": -1, "y": 100, "clicks": 1},
            {"action": "click", "x": True, "y": 100, "clicks": 1},
            {"action": "click", "x": 500, "y": 100, "clicks": 3},
            {"action": "click", "x": 500, "y": 100, "clicks": 1, "extra": "bad"},
            {"action": "key", "key": "CTRL_ALT_DELETE"},
            {"action": "text", "text": "whoami && del C:"},
            {"action": "text", "text": "line1\nline2"},
            {"action": "text", "text": "z" * 101},
            {"action": "launch", "url": "https://example.com"},
        ]
        with patch.object(agent, "_desktop_http") as remote:
            for action in actions:
                self.assertEqual(agent.desktop_input_action(action)["reason"],
                                 "desktop_action_invalid")
            remote.assert_not_called()

        with patch.object(agent, "desktop_status", return_value={
                "paired": True, "sharing": True, "control_enabled": False}), \
             patch.object(agent, "_desktop_http") as remote:
            self.assertEqual(agent.desktop_input_action({
                "action": "click", "x": 30, "y": 40, "clicks": 1,
            })["reason"], "desktop_control_not_authorized")
            remote.assert_not_called()

    def test_input_requires_separate_local_arm_and_returns_no_secrets(self):
        self.pair()
        action = {"action": "click", "x": 420, "y": 180, "clicks": 2}
        with patch.object(agent, "desktop_status", return_value={
                "paired": True, "sharing": True, "control_enabled": True}), \
             patch.object(agent, "_desktop_http", return_value=(
                 "application/json",
                 b'{"ok":true,"sharing":true,"control_enabled":true}')) as remote:
            result = agent.desktop_input_action(action)
        self.assertEqual(result, {"ok": True, "action": "click",
                                  "control_enabled": True})
        args = remote.call_args.args
        self.assertEqual(args[:2], ("/v1/action", VALID_SESSION))
        self.assertEqual(json.loads(remote.call_args.kwargs["payload"]), action)
        self.assertNotIn("session_token", json.dumps(result))
        self.assertTrue(agent.validate_desktop_action({
            "action": "key", "key": "ENTER"}))
        self.assertTrue(agent.validate_desktop_action({
            "action": "text", "text": "MetaHuman 5.8"}))

    def test_input_route_requires_worker_bearer_and_does_not_echo_text(self):
        server = agent.ThreadingHTTPServer(("127.0.0.1", 0), agent.Handler)
        server.token = "d" * 64
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            uri = f"http://127.0.0.1:{server.server_port}/v15/desktop/action"
            body = {"action": "text", "text": "Unreal Engine"}
            def call(headers):
                request = urllib.request.Request(
                    uri, method="POST", headers=headers,
                    data=json.dumps(body).encode("utf-8"))
                try:
                    with urllib.request.urlopen(request, timeout=3) as response:
                        return response.status, json.load(response)
                except urllib.error.HTTPError as err:
                    return err.code, json.loads(err.read())
            result, data = call({})
            self.assertEqual(result, 401)
            self.assertEqual(data["reason"], "unauthorized")
            result, data = call({"Authorization": "Bearer " + "d" * 64})
            self.assertEqual(result, 403)
            self.assertNotIn(body["text"], json.dumps(data))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

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
        self.assertIn("Enable Input", script)
        self.assertIn("Disable Input", script)
        self.assertIn("POST /v1/action", script)
        self.assertIn("Get-ControlActive", script)
        self.assertNotIn("Invoke-Expression", script)
        self.assertNotIn("keybd_event", script)


if __name__ == "__main__":
    unittest.main()
