"""Offline Windows VLESS startup, session privacy and fail-closed regressions."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import glacier_proxy_health29 as proxy


class ProxyHealth29Tests(unittest.TestCase):
    def test_ephemeral_config_is_private_and_removed_on_success(self):
        with tempfile.TemporaryDirectory() as temp:
            secret = "vless-uuid-test-only"
            with proxy.ephemeral_proxy_config(temp, {"uuid": secret}) as path:
                self.assertTrue(path.exists())
                self.assertEqual(json.loads(path.read_text())["uuid"], secret)
                self.assertEqual(path.parent, Path(temp))
                self.assertEqual(len(list(Path(temp).glob(".glacier-core-*.json"))), 1)
            self.assertFalse(path.exists())

    def test_ephemeral_config_removes_plaintext_on_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            try:
                with proxy.ephemeral_proxy_config(temp, {"uuid": "secret"}) as path:
                    raise ValueError("fake sing-box launch error")
            except ValueError:
                pass
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_ephemeral_config_never_overwrites_existing_config(self):
        with tempfile.TemporaryDirectory() as temp:
            legacy = Path(temp) / "runtime.json"
            legacy.write_text("untouched")
            with proxy.ephemeral_proxy_config(temp, {"uuid": "new"}) as path:
                self.assertNotEqual(path, legacy)
                self.assertEqual(legacy.read_text(), "untouched")
            self.assertEqual(legacy.read_text(), "untouched")

    def test_ephemeral_config_rejects_symlink_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            sub = p / "data"
            sub.mkdir()
            link = p / "link"
            try:
                link.symlink_to(sub, target_is_directory=True)
            except OSError:
                self.skipTest("Symlinks unavailable")
            with self.assertRaisesRegex(RuntimeError, "运行目录"):
                with proxy.ephemeral_proxy_config(link, {"uuid": "secret"}):
                    pass

    def test_local_listener_is_limited_to_loopback(self):
        with patch.object(proxy.socket, "create_connection") as dial:
            dial.return_value.__enter__ = Mock(return_value=None)
            dial.return_value.__exit__ = Mock(return_value=None)
            self.assertTrue(proxy.local_proxy_ready(17777))
            dial.assert_called_once_with(("127.0.0.1", 17777), timeout=0.2)
        for port in (0, -1, 65536, "127.0.0.1"):
            self.assertFalse(proxy.local_proxy_ready(port))

    def test_unavailable_proxy_never_falls_back_direct(self):
        with patch.object(proxy.socket, "create_connection", side_effect=OSError("refused")):
            self.assertFalse(proxy.local_proxy_ready(17777))

    def test_wait_until_process_listens_without_contacting_public_web(self):
        proc = Mock()
        proc.poll.return_value = None
        ready = Mock(side_effect=[False, False, True])
        current = [0.0]
        def sleep(seconds):
            current[0] += seconds
        proxy.await_proxy_ready(
            proc, 18082, timeout=3, interval=0.1,
            probe=ready, clock=lambda: current[0], pause=sleep,
        )
        self.assertEqual(current[0], 0.2)
        self.assertEqual(ready.call_count, 3)

    def test_core_exit_and_timeout_refuse_browser_connected_state(self):
        exited = Mock()
        exited.poll.return_value = 1
        with self.assertRaisesRegex(RuntimeError, "异常退出"):
            proxy.await_proxy_ready(exited, 19845, probe=lambda _: True)
        self.assertEqual(proxy.proxy_status_text(exited, 19845), (
            "● 代理已断开 · 点击重连", False))
        running = Mock()
        running.poll.return_value = None
        current = [0.0]
        def clock():
            return current[0]
        def sleep(value):
            current[0] += value
        with self.assertRaisesRegex(RuntimeError, "启动超时"):
            proxy.await_proxy_ready(
                running, 18995, timeout=0.3, interval=0.1,
                probe=lambda _: False, clock=clock, pause=sleep,
            )
        self.assertFalse(proxy.proxy_status_text(
            running, 18995, probe=lambda _: False)[1])

    def test_local_ready_only_claims_local_listener(self):
        running = Mock()
        running.poll.return_value = None
        self.assertEqual(proxy.proxy_status_text(running, 18998, probe=lambda _: True), (
            "● 本地代理就绪", True))
        self.assertEqual(proxy.proxy_status_text(running, 18998, probe=lambda _: False), (
            "● 代理启动中 · 点击重连", False))

    def test_windows_main_enforces_failclosed_and_encrypted_disk_storage(self):
        source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
        self.assertIn("with ephemeral_proxy_config(appdir(),config)", source)
        self.assertIn("await_proxy_ready(proc,port,timeout=12)", source)
        self.assertIn("runtime.json", source)
        self.assertIn("self.refresh_proxy_status29()", source)
        self.assertIn("self.reconnect_saved_proxy29", source)
        self.assertIn('dpapi(path.read_bytes(),True)', source)
        self.assertIn("--proxy-server=socks5://127.0.0.1:", source)
        self.assertIn("--disable-quic", source)
        self.assertIn("--force-webrtc-ip-handling-policy=disable_non_proxied_udp", source)
        self.assertNotIn("configfile.write_text(json.dumps(config)", source)


if __name__ == "__main__":
    unittest.main()
