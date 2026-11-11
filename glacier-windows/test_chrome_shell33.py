"""Actual Qt geometry, behavior and menu preservation for Chrome shell 33."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMenu, QToolButton, QTabBar
from glacier_chrome_shell33 import GlacierChromeShell33, CHROME_SHELL_QSS33, _install_tab_closers33
from test_desktop_ui32 import BrowserShellStub


class ChromeShell33Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["Glacier-33", "-platform", "offscreen"])

    def setUp(self):
        self.window = BrowserShellStub()
        self.window.more.setMenu(QMenu(self.window.more))
        GlacierChromeShell33.setup_chrome_shell33(self.window)

    def tearDown(self):
        self.window.close()

    def test_real_address_group_and_compact_sizes(self):
        w = self.window
        shell = w._chrome_omnibox_shell33
        self.assertEqual(shell.objectName(), "GlacierOmniboxShell33")
        self.assertEqual(w._navigation32.itemAt(3).widget(), shell)
        self.assertEqual([shell.layout().itemAt(i).widget() for i in range(3)],
                         [w._site_button30, w.address, w.bookmark_button])
        self.assertEqual(w._navigation_surface32.height(), 54)
        self.assertEqual(w.chrome_tab14.parentWidget().height(), 44)
        self.assertEqual(shell.height(), 39)
        self.assertLessEqual(w.address.maximumHeight(), 35)
        self.assertEqual(w.address.placeholderText(), "在 Google 中搜索或输入网址")
        self.assertFalse(w.tabs.tabBar().isVisible())

    def test_previous_handlers_keep_their_original_connections(self):
        w = self.window
        self.assertFalse(w.more.icon().isNull())
        self.assertFalse(w.downloads.icon().isNull())
        self.assertFalse(w._hub_button20.icon().isNull())
        self.assertFalse(w._site_button30.icon().isNull())
        self.assertFalse(w._account_button26.icon().isNull())
        self.assertEqual(w._account_button26.width(), 36)
        self.assertEqual(w._account_button26.text(), "")
        self.assertEqual(w._account_button26.accessibleName(), "Glacier 账号中心")
        self.assertEqual(w.more.popupMode(), QToolButton.ToolButtonPopupMode.InstantPopup)
        self.assertIsNotNone(w._utility_shelf32)
        # Original utility button remains wired to the shelf.
        w.more.menu().aboutToShow.emit()
        actions = [a for a in w.more.menu().actions()
                   if a.objectName() == "GlacierUtilityMenuAction33"]
        self.assertEqual(len(actions), 1)
        self.assertTrue(w._utility_shelf32.isHidden())
        actions[0].trigger()
        self.assertFalse(w._utility_shelf32.isHidden())
        w.legacy.click()
        self.assertEqual(w.clicks, 1)
        w.more.menu().aboutToShow.emit()
        self.assertEqual(len([a for a in w.more.menu().actions()
                              if a.objectName() == "GlacierUtilityMenuAction33"]), 1)


    def test_tab_close_icons_are_not_native_red_squares_and_survive_reorder(self):
        w = self.window
        bar = w.chrome_tab14
        bar.addTab("First")
        bar.addTab("Second")
        bar.setTabsClosable(True)
        _install_tab_closers33(bar)
        w.show()
        self.app.processEvents()
        buttons = [bar.tabButton(i, QTabBar.ButtonPosition.RightSide) for i in range(2)]
        for button in buttons:
            self.assertIsNotNone(button)
            self.assertEqual(button.objectName(), "GlacierTabClose33")
            self.assertIsInstance(button, QToolButton)
            self.assertFalse(button.icon().isNull())
            self.assertEqual(button.width(), 18)
        requested = []
        bar.tabCloseRequested.connect(requested.append)
        bar.moveTab(0, 1)
        self.app.processEvents()
        buttons[0].click()
        self.assertEqual(requested, [1])

    def test_address_focused_state_is_real_qt_focus_and_not_unsupported_css(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QFocusEvent
        shell = self.window._chrome_omnibox_shell33
        self.assertFalse(shell.property("focused"))
        self.app.sendEvent(self.window.address, QFocusEvent(QEvent.Type.FocusIn))
        self.assertTrue(shell.property("focused"))
        self.app.sendEvent(self.window.address, QFocusEvent(QEvent.Type.FocusOut))
        self.assertFalse(shell.property("focused"))
        self.assertIn('[focused="true"]', CHROME_SHELL_QSS33)
        self.assertNotIn(':focus-within', CHROME_SHELL_QSS33)

    def test_styling_is_presentation_only_and_double_setup_is_rejected(self):
        self.assertIn("GlacierOmniboxShell33", CHROME_SHELL_QSS33)
        self.assertIn("#f1f3f4", CHROME_SHELL_QSS33)
        for forbidden in ("socks5://", "QNetworkProxy", "dpapi", "requests.get"):
            self.assertNotIn(forbidden, CHROME_SHELL_QSS33)
        with self.assertRaisesRegex(RuntimeError, "only be installed once"):
            GlacierChromeShell33.setup_chrome_shell33(self.window)


if __name__ == "__main__":
    unittest.main()
