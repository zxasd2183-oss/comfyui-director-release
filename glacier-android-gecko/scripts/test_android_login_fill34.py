"""Fail-closed source regression guards for native GeckoView saved account fill."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
JAVA=ROOT/"app/src/main/java/cn/borealos/glacier/geckopreview"

class NativeAccountFillGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper=(JAVA/"GlacierAccountFill34.java").read_text(encoding="utf-8")
        cls.main=(JAVA/"MainActivity.java").read_text(encoding="utf-8")

    def test_only_explicit_account_card_click_uses_native_gecko_tree(self):
        self.assertIn('actions.add("填充当前页")',self.main)
        self.assertIn('fillCurrentSavedAccount(card)',self.main)
        self.assertIn('!accountCards.contains(card)',self.main)
        self.assertIn('!active.contextId.equals(accountCookieContext(card))',self.main)
        self.assertIn('web.getSession() != active.session',self.main)
        self.assertIn('!selectedProfile.equals(card.profile)',self.main)
        self.assertIn('GlacierAccountFill34.exactHttpsSite(active.url, card.site)',self.main)
        self.assertNotIn('evaluateJS(',self.helper)
        self.assertNotIn('loadUri(',self.helper)
        self.assertNotIn('requestSubmit(',self.helper)
        self.assertNotIn('.submit(',self.helper)

    def test_native_nodes_are_scoped_to_first_party_visible_inputs(self):
        src=self.helper
        for check in ('exactHttpsSite(currentUrl, card.site)',
                      '!exactNodeSite(node.getDomain(), card.site)',
                      '!session.isVisible(node)',
                      'node.getEnabled()', 'node.getFocusable()',
                      'Autofill.Hint.USERNAME','Autofill.Hint.EMAIL_ADDRESS',
                      'Autofill.Hint.PASSWORD',
                      'if (password != null) return 0',
                      'if (username != null) return 0',
                      'session.autofill(values)',
                      'if (++count > 500) return 0'):
            self.assertIn(check,src)
        self.assertNotIn('android.util.Log',src)
        self.assertNotIn('CookieManager',src)
        self.assertNotIn('getUserInfo() == null',src)

if __name__=="__main__":
    unittest.main()
