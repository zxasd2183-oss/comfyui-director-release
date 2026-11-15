"""Source guards for Android per-account GeckoView Cookie isolation."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "app/src/main/java/cn/borealos/glacier/geckopreview"

class AndroidAccountSessionGuards(unittest.TestCase):
    def test_encrypted_snapshot_keeps_original_default_cookie_context(self):
        source = (JAVA / "BrowserTabStore.java").read_text(encoding="utf-8")
        self.assertIn('row.optString("context_id", "glacier-" + profile)', source)
        self.assertIn('obj.put("context_id", item.contextId)', source)
        self.assertIn("validContextId(item.profile, item.contextId)", source)
        self.assertIn("glacier-account-", source)

    def test_new_account_context_is_hashed_and_used_before_session_opens(self):
        source = (JAVA / "MainActivity.java").read_text(encoding="utf-8")
        self.assertIn('MessageDigest.getInstance("SHA-256")', source)
        self.assertIn("accountCookieContext(card)", source)
        self.assertIn("createTab(card.profile, context)", source)
        self.assertIn(".contextId(contextId)", source)
        self.assertIn("createSession(row.profile, row.contextId)", source)
        self.assertIn("tab.contextId", source)
        self.assertIn("parent.contextId", source)
        self.assertNotIn("CookieManager.setCookie", source)
        self.assertNotIn("cookieSync", source)

    def test_account_session_requires_saved_card_and_keeps_profile(self):
        source = (JAVA / "MainActivity.java").read_text(encoding="utf-8")
        self.assertIn("accountCards.contains(card)", source)
        self.assertIn("BrowserAccountsStore.valid(card)", source)
        self.assertIn("在独立会话中打开", source)
        self.assertIn("selectedProfile = next.profile", source)
        self.assertIn("GlacierCloudSync.encrypt", source)

if __name__ == "__main__":
    unittest.main()
