"""Enforce compositor-risk mitigations on every Android RC checkout."""
from pathlib import Path
import unittest

class GeckoMainThreadGuards(unittest.TestCase):
    def test_no_automatic_screenshot_after_page_stop(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "app/src/main/java/cn/borealos/glacier/geckopreview/MainActivity.java").read_text(encoding="utf-8")
        self.assertNotIn("() -> captureTabThumbnail(target)", source)
        switch = source.split("private void switchTo(Tab next) {", 1)[1].split("private void updateChrome()", 1)[0]
        self.assertNotIn("captureTabThumbnail(active)", switch)

    def test_thumbnail_encoding_not_on_ui_thread(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "app/src/main/java/cn/borealos/glacier/geckopreview/MainActivity.java").read_text(encoding="utf-8")
        capture = source.split("private void captureTabThumbnail(Tab tab) {", 1)[1].split("private void restoreLibrary()", 1)[0]
        self.assertIn("tabSaveQueue.execute(() -> {", capture)
        self.assertIn("Bitmap.createScaledBitmap", capture)
        self.assertIn("runOnUiThread", capture)

if __name__ == "__main__":
    unittest.main()
