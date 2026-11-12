"""Real Qt integration gate: Glacier account UI is visible, clickable, and safe.

No network or actual credentials. Headless offscreen Qt must work in CI.
"""
import os
import gc
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QWidget
from glacier_account_center26 import GlacierAccountCenter26, account_label26


class FakeWindow(QWidget, GlacierAccountCenter26):
    def __init__(self):
        super().__init__()
        self._sync_state23 = {}
        self.logins = 0
        self.registrations = 0

    def _sync_login23(self, **fields):
        self.logins += 1
        self.last_login_fields = fields

    def _sync_register23(self, **fields):
        self.registrations += 1
        self.last_register_fields = fields

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

    def manage_accounts22(self):
        pass


class AccountCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        # Offscreen Windows Qt can AV on interpreter exit if a modal dialog
        # or unparented layout survives the QApplication. Clean them now.
        for widget in list(QApplication.topLevelWidgets()):
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        gc.collect()

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

    def test_profile_menu_is_anchored_popup_not_separate_dialog(self):
        window = FakeWindow()
        window.resize(980, 600)
        layout = QHBoxLayout()
        window.setup_account_center26(layout)
        window.show()
        self.app.processEvents()
        menu = window.show_account_center26()
        self.app.processEvents()
        self.assertEqual(menu.objectName(), "GlacierProfilePopover37")
        self.assertTrue(bool(menu.windowFlags() & Qt.WindowType.Popup))
        self.assertFalse(isinstance(menu, QDialog))
        self.assertTrue(menu.isVisible())
        self.assertIn("登录 Glacier 账号", [
            x.text() for x in menu.findChildren(QPushButton)
        ])
        self.assertIn("网站账号和密码", [
            x.text() for x in menu.findChildren(QPushButton)
        ])
        self.assertEqual(window.logins, 0)
        # The user can dismiss the profile menu without logging in.
        menu.close()
        window.close()

    def test_pending_device_uses_approval_action_not_fake_success(self):
        window = FakeWindow()
        window.setup_account_center26(QHBoxLayout())
        window._sync_state23 = {
            "token": "dummy", "approved": False, "username": "demo"
        }
        menu = window.show_account_center26()
        labels = [b.text() for b in menu.findChildren(QPushButton)]
        self.assertIn("检查设备授权", labels)
        self.assertNotIn("上传加密资料", labels)
        self.assertNotIn("管理已授权设备", labels)
        menu.close()
        window.close()

    def test_approved_device_lists_real_sync_actions(self):
        window = FakeWindow()
        window.setup_account_center26(QHBoxLayout())
        window._sync_state23 = {
            "token": "dummy", "approved": True,
            "username": "demo", "auto_enabled": False
        }
        menu = window.show_account_center26()
        labels = [b.text() for b in menu.findChildren(QPushButton)]
        for label in ("网站账号和密码", "管理已授权设备",
                      "上传加密资料", "下载加密资料", "开启自动同步",
                      "退出 Glacier 账号"):
            self.assertIn(label, labels)
        self.assertNotIn("创建 Glacier 账号", labels)
        menu.close()
        window.close()

    def test_one_screen_login_collects_all_fields(self):
        window = FakeWindow()
        def submit():
            modal = QApplication.activeModalWidget()
            self.assertIsInstance(modal, QDialog)
            entries = modal.findChildren(QLineEdit)
            self.assertEqual(len(entries), 3)
            entries[0].setText("https://sync.borealos.cn")
            entries[1].setText("test-user")
            entries[2].setText("synthetic-password-only")
            modal.findChild(QDialogButtonBox).button(
                QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(0, submit)
        self.assertTrue(window._account_form26(False))
        self.assertEqual(window.logins, 1)
        self.assertEqual(window.last_login_fields["username"], "test-user")
        self.assertEqual(window.last_login_fields["base"], "https://sync.borealos.cn")
        window.close()

    def test_invalid_password_does_not_dismiss_form(self):
        window = FakeWindow()
        observed = []
        def interact():
            modal = QApplication.activeModalWidget()
            self.assertIsInstance(modal, QDialog)
            inputs = modal.findChildren(QLineEdit)
            inputs[0].setText("https://sync.borealos.cn")
            inputs[1].setText("test-user")
            inputs[2].setText("short")
            box = modal.findChild(QDialogButtonBox)
            with patch.object(QMessageBox, "warning", return_value=None):
                box.button(QDialogButtonBox.StandardButton.Ok).click()
            observed.append(modal.isVisible())
            observed.append(window.logins)
            modal.reject()
        QTimer.singleShot(0, interact)
        self.assertFalse(window._account_form26(False))
        self.assertEqual(observed, [True, 0])
        window.close()

    def test_button_label_refreshes_when_signed_in(self):
        window = FakeWindow()
        window.setup_account_center26(QHBoxLayout())
        window._sync_state23 = {"token": "dummy", "approved": True, "username": "demo"}
        window.refresh_account_center26()
        self.assertIn("demo", window._account_button26.text())
        window.close()


if __name__ == "__main__":
    unittest.main()
