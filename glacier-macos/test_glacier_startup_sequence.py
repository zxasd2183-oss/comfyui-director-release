"""Glacier direct-launch regression: no app-owned splash or artificial delay."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name("main.py")

class DirectLaunchTests(unittest.TestCase):
    def source(self):
        return SOURCE.read_text(encoding="utf-8")

    def tree(self):
        return ast.parse(self.source())

    def test_new_tab_home_remains_a_real_local_page(self):
        tree = self.tree()
        browser = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Browser")
        method = next(n for n in browser.body if isinstance(n, ast.FunctionDef) and n.name == "new_tab")
        calls = [n for n in ast.walk(method)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "setUrl"]
        self.assertTrue(any("QUrl.fromLocalFile" in ast.unparse(c) for c in calls))
        self.assertTrue(any(isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Name)
                            and n.func.id == "ensure_offline_home_file"
                            for n in ast.walk(method)))

    def test_entrypoint_opens_main_window_without_separate_splash(self):
        source = self.source()
        tree = self.tree()
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        main_source = ast.get_source_segment(source, main)
        self.assertNotIn("show_glacier_splash", source)
        self.assertNotIn("reveal_browser_after_splash", source)
        self.assertNotIn("splash=", main_source)
        self.assertEqual(main_source.count("win.show()"), 1)
        self.assertLess(main_source.index("win=Browser(proc,port)"), main_source.index("win.show()"))
        self.assertLess(main_source.index("QNetworkProxy.setApplicationProxy"), main_source.index("win.show()"))
        self.assertLess(main_source.index('QTWEBENGINE_CHROMIUM_FLAGS'), main_source.index("QApplication("))
        self.assertNotIn("min_visible_ms", main_source)

    def test_startup_does_not_enable_direct_proxy_fallback(self):
        source = self.source()
        self.assertIn("--proxy-server=socks5://127.0.0.1:", source)
        self.assertIn("disable_non_proxied_udp", source)
        self.assertIn("QNetworkProxy.ProxyType.Socks5Proxy", source)


if __name__ == "__main__":
    unittest.main()
