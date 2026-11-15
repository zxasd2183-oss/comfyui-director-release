"""Glacier account login session isolation: no passwords or Cookie export."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import tempfile
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import glacier_accounts22 as accounts


class FakeProfile:
    class PersistentCookiesPolicy:
        AllowPersistentCookies = 1

    def __init__(self, name, owner):
        self.name = name
        self.owner = owner
        self.path = ""
        self.cache = ""
        self.cookies = SimpleNamespace(deleteAllCookies=self.deleteAll)
        self.deleted = 0

    def setPersistentStoragePath(self, path):
        self.path = path

    def setCachePath(self, path):
        self.cache = path

    def setPersistentCookiesPolicy(self, policy):
        assert policy == self.PersistentCookiesPolicy.AllowPersistentCookies

    def cookieStore(self):
        return self.cookies

    def deleteAll(self):
        self.deleted += 1


class Host(accounts.GlacierAccounts22):
    def __init__(self, directory):
        self._accounts_doc22 = {"schema": 1, "accounts": []}
        self._account_profiles22 = {}
        self._account_profiles_root22 = Path(directory) / "account-profiles-v1"
        self._workspace_doc17 = {"active": "default"}
        self.opened = []
        self.status = []
        self.statusBar = lambda: SimpleNamespace(
            showMessage=lambda value, ms: self.status.append(value))

    def new_tab(self, account_profile=None):
        view = SimpleNamespace(
            profile=account_profile,
            setUrl=lambda url: self.opened.append((account_profile, url.toString())))
        return view


class AccountSessions(TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.host = Host(self.dir.name)
        self.patcher = patch.object(accounts, "QWebEngineProfile", FakeProfile)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.dir.cleanup)

    def card(self, username, site="github.com", space="private", name="primary"):
        card = {"site": site, "username": username, "name": name,
                "password": "test-secret-not-a-path", "space": space}
        self.host._accounts_doc22["accounts"].append(card)
        return card

    def test_same_login_reuses_session_and_rename_does_not_change_identity(self):
        a = self.card("alice@test.invalid")
        self.assertTrue(self.host.open_account_session22(a))
        p = self.host.opened[-1][0]
        self.assertTrue(self.host.open_account_session22(a))
        self.assertIs(self.host.opened[-1][0], p)
        a["name"] = "renamed"
        self.assertTrue(self.host.open_account_session22(a))
        self.assertIs(self.host.opened[-1][0], p)
        self.assertEqual(self.host.opened[-1][1], "https://github.com/")
        self.assertIn("account-profiles-v1", p.path)
        for secret in ("alice", "github", "test-secret", "primary"):
            self.assertNotIn(secret, p.path)
            self.assertNotIn(secret, p.name)

    def test_different_website_logins_and_workspaces_never_share_profile(self):
        a = self.card("alice@test.invalid")
        b = self.card("bob@test.invalid", name="other")
        c = self.card("alice@test.invalid", site="chatgpt.com")
        pa = self.host._profile_for_saved_account22(a)
        pb = self.host._profile_for_saved_account22(b)
        pc = self.host._profile_for_saved_account22(c)
        self.assertEqual(len({pa.path, pb.path, pc.path}), 3)
        self.assertIsNot(pa, pb)
        self.assertIsNot(pa, pc)
        self.host._workspace_doc17["active"] = "work-team"
        d = self.card("alice@test.invalid", space="work")
        self.assertIsNot(pa, self.host._profile_for_saved_account22(d))

    def test_forged_and_wrong_space_accounts_cannot_open_profile(self):
        card = self.card("alice@test.invalid")
        forged = dict(card)
        forged["site"] = "github.com.evil.test"
        self.assertIsNone(self.host._profile_for_saved_account22(forged))
        self.assertIsNone(self.host._profile_for_saved_account22(
            {**card, "username": "not-saved"}))
        self.host._workspace_doc17["active"] = "work-team"
        self.assertFalse(self.host.open_account_session22(card))

    def test_clear_only_selected_accounts_cookie_jar_after_explicit_consent(self):
        from PySide6.QtWidgets import QMessageBox
        alice = self.card("alice@test.invalid")
        bob = self.card("bob@test.invalid", name="bob")
        pa = self.host._profile_for_saved_account22(alice)
        pb = self.host._profile_for_saved_account22(bob)
        with patch.object(accounts.QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No):
            self.assertFalse(self.host.clear_account_session_cookies22(alice))
        self.assertEqual(pa.deleted, 0)
        with patch.object(accounts.QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(self.host.clear_account_session_cookies22(alice))
        self.assertEqual(pa.deleted, 1)
        self.assertEqual(pb.deleted, 0)
        self.assertEqual(len(self.host.status), 1)

    def test_desktop_tab_pages_bind_cookies_to_explicit_account_profile(self):
        root = Path(__file__).resolve().parents[1]
        for platform in ("glacier-windows", "glacier-macos"):
            with self.subTest(platform=platform):
                src = (root / platform / "main.py").read_text(encoding="utf-8")
                self.assertIn("QWebEnginePage(profile,self)", src)
                self.assertIn("v=Page(self,account_profile)", src)
                self.assertIn("self._glacier_account_profile22", src)
        tabs = (root / "glacier-windows/glacier_tabs19.py").read_text(encoding="utf-8")
        self.assertIn('getattr(view, "_glacier_account_profile22", None)', tabs)


if __name__ == "__main__":
    import unittest
    unittest.main()
