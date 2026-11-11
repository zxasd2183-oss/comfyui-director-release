"""Qt regression for exclusive standalone splash to browser handoff."""
import os
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from glacier_splash import show_glacier_splash, reveal_browser_after_splash


class WatchedBrowser(QWidget):
    def __init__(self, splash):
        super().__init__()
        self.splash = splash
        self.show_count = 0
        self.overlap = False

    def showEvent(self, event):
        self.show_count += 1
        self.overlap = self.overlap or self.splash.isVisible()
        super().showEvent(event)


class StartupSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["Glacier-Startup-QA", "-platform", "offscreen"])

    def test_splash_is_alone_then_fully_closes_before_main_window(self):
        splash = show_glacier_splash("QA")
        window = WatchedBrowser(splash)
        self.assertTrue(splash.isVisible())
        self.assertFalse(window.isVisible())
        events = []
        remaining = reveal_browser_after_splash(
            splash, window, min_visible_ms=120,
            on_reveal=lambda: events.append(("revealed", splash.isVisible(), window.isVisible())))
        self.assertGreaterEqual(remaining, 0)
        QTest.qWait(35)
        self.assertFalse(window.isVisible())
        QTest.qWait(150)
        self.assertFalse(splash.isVisible())
        self.assertTrue(window.isVisible())
        self.assertEqual(window.show_count, 1)
        self.assertFalse(window.overlap)
        self.assertEqual(events, [("revealed", False, True)])
        window.close()

    def test_browser_never_shown_while_loading_and_duplicate_handoff_refused(self):
        splash = show_glacier_splash("QA")
        window = WatchedBrowser(splash)
        reveal_browser_after_splash(splash, window, min_visible_ms=90)
        with self.assertRaisesRegex(RuntimeError, "already scheduled"):
            reveal_browser_after_splash(splash, window, min_visible_ms=90)
        QTest.qWait(120)
        self.assertFalse(window.overlap)
        window.close()


if __name__ == "__main__":
    unittest.main()
