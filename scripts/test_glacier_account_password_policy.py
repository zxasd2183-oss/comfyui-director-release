"""Guard Glacier *login* password length across Windows/macOS/Android.

The cloud encryption passphrase remains a separate >=12-character secret.
No real credentials, token, invite, or network calls are used.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LoginPasswordPolicyTests(unittest.TestCase):
    def test_desktop_registration_and_login_forms_match(self):
        a = (ROOT / "glacier-windows/glacier_account_center26.py").read_text()
        b = (ROOT / "glacier-macos/glacier_account_center26.py").read_text()
        self.assertEqual(a, b)
        self.assertIn('password.setPlaceholderText("至少 8 个字符")', a)
        self.assertIn("len(secret) < 8", a)
        self.assertIn("至少 8 位的密码。", a)
        self.assertNotIn("len(secret) < 12", a)

    def test_desktop_registration_logic_is_min8_but_e2e_vault_min12(self):
        a = (ROOT / "glacier-windows/glacier_sync23.py").read_text()
        b = (ROOT / "glacier-macos/glacier_sync23.py").read_text()
        self.assertEqual(a, b)
        self.assertIn('if len(password) < 8:', a)
        self.assertIn('Login password must contain at least 8 characters', a)
        self.assertIn('登录密码（至少 8 位）', a)
        self.assertIn('if space not in ("private", "work") or len(password) < 12:', a)
        self.assertIn('if len(value) < 12:', a)

    def test_android_registration_login_min8_e2e_vault_min12(self):
        ui = (ROOT / "glacier-android-gecko/app/src/main/java/"
                     "cn/borealos/glacier/geckopreview/MainActivity.java").read_text()
        sync = (ROOT / "glacier-android-gecko/app/src/main/java/"
                       "cn/borealos/glacier/geckopreview/GlacierCloudSync.java").read_text()
        self.assertIn('cloudField(form,"登录密码（至少 8 位）"', ui)
        self.assertIn('server.isEmpty()||password.length()<8||username.length()<3', ui)
        self.assertIn('if(password.length()<12)', ui)
        self.assertIn('if(passphrase==null||passphrase.length()<12||salt.length!=16)', sync)

    def test_invitation_must_still_be_supplied_to_server(self):
        win = (ROOT / "glacier-windows/glacier_sync23.py").read_text()
        android = (ROOT / "glacier-android-gecko/app/src/main/java/"
                          "cn/borealos/glacier/geckopreview/MainActivity.java").read_text()
        self.assertIn('"POST", "/v1/register", {"invite": invite', win)
        self.assertIn('if(register)payload.put("invite",invitation);', android)


if __name__ == "__main__":
    unittest.main()
