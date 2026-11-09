"""Real Qt integration gate: Glacier account UI is visible, clickable, and safe.

No network or actual credentials. Headless offscreen Qt must work in CI.
"""
import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget
from glacier_account_center26 import GlacierAccountCenter26, account_label26


class FakeWindow(QWidget, GlacierAccountCenter26):
    def __init__(self):
        super().__init__()
        self._sync_state23 = {}
        self.logins = 0
        self.registrations = 0

    def _sync_login23(self):
        self.logins += 1

    def _sync_register23(self):
        self.registrations += 1

    def _sync_error23(self, e):
        raise AssertionError("Unexpected account handler error")

    def _sync_logout23(self):
        self._sync_state23.clear()

    def _sync_activate23(self):
        pass

    def _sync_devices23(self):
        pass

    def _sync_push23(self):
        pass

    def _sync_pull23(self):
        pass

    def _sync_enable_auto23(self):
        pass

    def _sync_disable_auto23(self):
        pass

    def show_accounts22(self):
        pass


class AccountCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_exactly_visible_login_button_from_fresh_install(self):
        window = FakeWindow()
        bar = QHBoxLayout()
        window.setup_account_center26(bar)
        self.assertTrue(window._account_button26.isVisibleTo(window))
        self.assertIn("登录 Glacier", window._account_button26.text())
        self.assertTrue(window._account_button26.isEnabled())
        window.close()

    def test_logged_in_and_device_pending_labels(self):
        self.assertIn("登录", account_label26({})[0])
        self.assertIn("等待", account_label26({"token": "dummy", "approved": False})[0])
        self.assertEqual(account_label26(
            {"token": "dummy", "approved": True, "username": "user-demo"})[0], "user-demo")

    def test_button_label_refreshes_when_signed_in(self):
        window = FakeWindow()
        window.setup_account_center26(QHBoxLayout())
        window._sync_state23 = {"token": "dummy", "approved": True, "username": "demo"}
        window.refresh_account_center26()
        self.assertIn("demo", window._account_button26.text())
        window.close()


if __name__ == "__main__":
    unittest.main()
