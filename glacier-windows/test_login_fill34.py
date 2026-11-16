"""Security and interaction tests for click-to-fill on desktop website accounts."""
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QUrl
from glacier_accounts22 import GlacierAccounts22, build_login_fill_script22

ROOT = Path(__file__).resolve().parent


class FakePage:
    def __init__(self, profile, url):
        self._profile = profile
        self._url = QUrl(url)
        self.calls = []

    def profile(self):
        return self._profile

    def url(self):
        return self._url

    def runJavaScript(self, script, world_id, callback):
        self.calls.append((script, world_id))
        callback("filled")


class FakeView:
    def __init__(self, page, url):
        self._page = page
        self._url = QUrl(url)

    def page(self):
        return self._page

    def url(self):
        return self._url


class Host(GlacierAccounts22):
    def __init__(self, account, profile, url="https://github.com/login"):
        self.account = account
        self.profile = profile
        self.messages = []
        self.page = FakePage(profile, url)
        self.view = FakeView(self.page, url)
        self._workspace_doc17 = {"active": "default"}
        self._accounts_doc22 = {"schema": 1, "accounts": [account]}

    def _profile_for_saved_account22(self, record):
        if record != self.account or self._account_space22() != "private":
            return None
        return self.profile

    def current(self):
        return self.view

    def statusBar(self):
        return SimpleNamespace(showMessage=lambda message, duration:
                               self.messages.append(message))


class LoginFillSafety(unittest.TestCase):
    def setUp(self):
        self.account = {"site": "github.com", "username": "susan@example.invalid",
                        "password": "example-secret-34", "space": "private",
                        "name": "test identity"}
        self.profile = object()
        self.host = Host(self.account, self.profile)

    def test_fill_requires_explicit_current_account_profile_and_origin(self):
        self.assertTrue(self.host.fill_account_form22(self.account))
        self.assertEqual(len(self.host.page.calls), 1)
        self.assertEqual(self.host.page.calls[0][1], 1)  # Qt ApplicationWorld
        self.assertIn("已填入账号和密码", self.host.messages[0])
        self.assertNotIn("example-secret-34", self.host.messages[0])
        self.assertNotIn("susan@example.invalid", self.host.messages[0])
        self.assertFalse(self.host.fill_account_form22({**self.account, "username": "forged"}))
        self.assertEqual(len(self.host.page.calls), 1)
        self.host._workspace_doc17["active"] = "work-team"
        self.assertFalse(self.host.fill_account_form22(self.account))
        self.assertEqual(len(self.host.page.calls), 1)

    def test_rejects_cross_site_navigation_even_with_correct_profile(self):
        for url in ("https://login.github.com/", "https://github.com.evil.invalid/",
                    "http://github.com/", "https://github.com:444/",
                    "file:///accounts", "https://github.com/"):
            with self.subTest(url=url):
                self.host.view._url = QUrl(url)
                self.host.page._url = QUrl("https://github.com/login")
                result = self.host.fill_account_form22(self.account)
                if url == "https://github.com/":
                    self.assertTrue(result)
                else:
                    self.assertFalse(result)
        self.assertEqual(len(self.host.page.calls), 1)

    def test_page_navigation_race_is_refused_before_injection(self):
        self.host.page._url = QUrl("https://untrusted.invalid")
        self.assertFalse(self.host.fill_account_form22(self.account))
        self.assertEqual(self.host.page.calls, [])
        self.host.page._url = QUrl("https://github.com/login")
        self.host.view._page = FakePage(object(), "https://github.com/login")
        self.assertFalse(self.host.fill_account_form22(self.account))

    def test_script_rejects_malformed_accounts_and_escapes_credentials(self):
        for site in ("", "github.com:443", "github.com.evil/path"):
            with self.assertRaises(ValueError):
                build_login_fill_script22(site, "user", "secret")
        with self.assertRaises(ValueError):
            build_login_fill_script22("github.com", "", "secret")
        with self.assertRaises(ValueError):
            build_login_fill_script22("github.com", "user", "x" * 2049)
        script = build_login_fill_script22(
            "github.com", 'user";window.location="https://evil.test', 'x";alert(1)')
        self.assertIn(r'user\";window.location=', script)
        self.assertIn(r'x\";alert(1)', script)
        self.assertNotIn("requestSubmit(", script.replace("// Never call submit(), requestSubmit(), click() or navigate().", ""))
        self.assertNotIn(".submit(", script)

    @unittest.skipUnless(shutil.which("node"), "Node.js required for JS DOM security cases")
    def test_generated_script_really_executes_dom_security_cases(self):
        script = build_login_fill_script22(
            "github.com", "susan@example.invalid", "example-secret-34")
        test = ROOT / "test_login_fill_browser34.js"
        run = subprocess.run(["node", str(test)], input=script, text=True,
                             capture_output=True, timeout=10, check=False)
        self.assertEqual(run.returncode, 0,
                         "JS mock failed: " + run.stderr[:1200])
        self.assertIn("PASS: HTTPS exact host", run.stdout)


if __name__ == "__main__":
    unittest.main()
