"""Glacier Windows / macOS icon integration, packaging and file regression."""
from pathlib import Path
import struct
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

class GlacierDesktopBrand(unittest.TestCase):
    def test_master_is_valid_three_peak_vector(self):
        src = ROOT / "assets/glacier-browser.svg"
        xml = ET.parse(src).getroot()
        self.assertTrue(xml.tag.endswith("svg"))
        self.assertEqual(xml.attrib.get("viewBox"), "0 0 1024 1024")
        self.assertIn("glacier peaks", src.read_text(encoding="utf8").lower())

    def test_one_identical_loader_both_platforms(self):
        win = (ROOT / "glacier-windows/glacier_brand_icon.py").read_bytes()
        mac = (ROOT / "glacier-macos/glacier_brand_icon.py").read_bytes()
        self.assertEqual(win, mac)
        self.assertIn(b"_MEIPASS", win)
        self.assertIn(b"GlacierBrowser.png", win)

    def test_windows_native_exe_and_setup_icon(self):
        wf = (ROOT / ".github/workflows/glacier-rc-windows.yml").read_text(encoding="utf-8")
        self.assertIn("--icon assets/GlacierBrowser.ico", wf)
        self.assertIn("SetupIconFile=assets\\GlacierBrowser.ico", wf)
        self.assertIn("--add-data 'assets/GlacierBrowser.png;assets'", wf)
        shell = (ROOT / "glacier-windows/glacier_chrome_shell33.py").read_text(encoding="utf-8")
        self.assertIn("self.setWindowIcon(glacier_icon())", shell)
        self.assertIn("app.setWindowIcon(glacier_icon())", (ROOT / "glacier-windows/main.py").read_text(encoding="utf-8"))

    def test_mac_native_app_bundle_dock_icon(self):
        wf = (ROOT / ".github/workflows/glacier-rc-macos.yml").read_text(encoding="utf-8")
        self.assertIn("--icon assets/GlacierBrowser.icns", wf)
        self.assertIn("--add-data 'assets/GlacierBrowser.png:assets'", wf)
        self.assertIn("CFBundleIconFile", wf)
        self.assertIn("app.setWindowIcon(glacier_icon())", (ROOT / "glacier-macos/main.py").read_text(encoding="utf-8"))

    def test_generated_icon_files_if_present(self):
        seen = 0
        for platform in ("windows", "macos"):
            folder = ROOT / f"glacier-{platform}/assets"
            master = folder / "GlacierBrowser.png"
            if not master.exists():
                continue
            seen += 1
            data = master.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (1024, 1024))
            ext = "ico" if platform == "windows" else "icns"
            binary = (folder / f"GlacierBrowser.{ext}").read_bytes()
            self.assertGreater(len(binary), 2000)
            if ext == "ico":
                self.assertEqual(struct.unpack("<HHH", binary[:6]), (0, 1, 7))
            else:
                self.assertEqual(binary[:4], b"icns")
        self.assertGreater(seen, 0, "Generate icon assets before validating them")

if __name__ == "__main__":
    unittest.main()
