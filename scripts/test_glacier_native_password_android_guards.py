"""Static safety gate for Android native login capture & per-session filling.

Actual APK/GeckoView compilation and 15 emulator checks are executed by the
separate Android RC workflow; these source assertions prevent accidental
fallback to global unscoped login storage or background-tab fill.
"""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"glacier-android-gecko/app/src/main/java/cn/borealos/glacier/geckopreview"
MAIN=SRC/"MainActivity.java"
NATIVE=SRC/"GlacierNativePasswordSave.java"
FILL=SRC/"GlacierAccountFill34.java"


class AndroidNativePasswordManagerGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main=MAIN.read_text(encoding="utf-8")
        cls.native=NATIVE.read_text(encoding="utf-8")
        cls.fill=FILL.read_text(encoding="utf-8")

    def test_submitted_login_is_gecko_native_and_saved_only_after_consent(self):
        for phrase in ("public GeckoResult<GeckoSession.PromptDelegate.PromptResponse> onLoginSave(",
                       "promptToSaveWebsitePassword(source, request)",
                       "setPositiveButton(updating?\"更新密码\":\"保存密码\"",
                       "if(!persistAccountVault(candidate))",
                       "pending.complete(request.confirm(offered))",
                       "active.session!=source","selectedProfile.equals(proposed.profile)"):
            self.assertIn(phrase,self.main)
        self.assertNotIn("setAutocompleteStorageDelegate(",self.main)
        self.assertNotIn("evaluateJavascript(",self.main)

    def test_explicit_password_choice_does_one_only_scoped_fill(self):
        for term in ("Tab tab = createTab(card.profile, context);",
                     "tab.pendingAccountFill=fill?card:null;",
                     "tab.lastAccountPromptSite=card.site;",
                     "target.pendingAccountFill=null;",
                     "requestedFill!=null && target==active",
                     "target.contextId.equals(accountCookieContext(requestedFill))",
                     "GlacierAccountFill34.exactHttpsSite(target.url,requestedFill.site)",
                     "fillCurrentSavedAccount(requestedFill);",
                     "if(failed!=null)failed.pendingAccountFill=null;",
                     "openSavedAccountSessionAndFill(matchedCards.get(which))",
                     "actions.add(\"使用此账号并填充\")"):
            self.assertIn(term,self.main)
        self.assertNotIn("requestSubmit()",self.main)

    def test_backend_username_profile_and_form_action_are_validated(self):
        self.assertIn("site.equals(BrowserAccountsStore.siteFromUrl(entry.origin))",self.native)
        self.assertIn("site.equals(BrowserAccountsStore.siteFromUrl(entry.formActionOrigin))",self.native)
        self.assertIn("profile,site,label,entry.username,entry.password",self.native)
        self.assertIn("BrowserAccountsStore.valid(next)",self.native)
        self.assertIn("GlacierAccountFill34.exactHttpsSite",self.main)

    def test_no_plaintext_in_telemetry(self):
        for forbidden in ("Log.d(\"Password\"", "Log.i(\"Password\"", "System.out.println(entry.password)",
                          "System.out.println(proposed.password)"):
            self.assertNotIn(forbidden,self.main+self.native)
        self.assertIn("no DOM password scraping",self.native)
        self.assertIn("fill(active.session",self.main)


if __name__=="__main__":
    unittest.main()
