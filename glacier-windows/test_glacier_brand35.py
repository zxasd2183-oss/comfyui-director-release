"""Native and WebEngine regressions for the original Glacier vector logo."""
import os
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray
from PySide6.QtSvg import QSvgRenderer
from glacier_brand35 import GLACIER_BRAND_SVG35
from glacier_shell20 import glacier_home20


class GlacierBrand35Tests(unittest.TestCase):
    def test_wordmark_is_real_self_contained_svg_not_emoji_or_html_text(self):
        logo = GLACIER_BRAND_SVG35
        self.assertIn('viewBox="0 0 900 172"', logo)
        self.assertIn('aria-label="Glacier"', logo)
        self.assertGreaterEqual(logo.count("<path"), 12)
        self.assertNotIn("<text", logo.lower())
        self.assertNotIn("❄", logo)
        self.assertNotIn("<script", logo.lower())
        self.assertNotIn("http://", logo.replace('xmlns="http://www.w3.org/2000/svg"', ""))

    def test_real_qt_svg_renderer_can_parse_shared_logo(self):
        renderer = QSvgRenderer(QByteArray(GLACIER_BRAND_SVG35.encode("utf-8")))
        self.assertTrue(renderer.isValid())
        self.assertEqual(renderer.defaultSize().width(), 900)
        self.assertEqual(renderer.defaultSize().height(), 172)

    def test_local_new_tab_reuses_same_vector_without_external_asset(self):
        home = glacier_home20()
        self.assertIn(GLACIER_BRAND_SVG35, home)
        self.assertEqual(home.count('aria-label="Glacier"'), 1)
        self.assertIn('class="wordmark"', home)
        self.assertNotIn("<!--GLACIER_VECTOR_LOGO35-->", home)
        self.assertNotIn("❄", home)
        self.assertNotIn("<script", home.lower())


if __name__ == "__main__":
    unittest.main()
