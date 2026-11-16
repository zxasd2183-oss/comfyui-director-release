"""Source-level regression guards for Glacier Android manual cloud vault transfer.

Keystore failure must never become an empty remote vault, and replacing
existing remote/local account cards always requires user confirmation.
"""
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] /
          "app/src/main/java/cn/borealos/glacier/geckopreview/MainActivity.java")


class CloudVaultSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = SOURCE.read_text(encoding="utf-8")

    def part(self, begin, end):
        first = self.code.index(begin)
        last = self.code.index(end, first + len(begin))
        return self.code[first:last]

    def test_locked_vault_never_starts_manual_upload(self):
        method = self.part("private void cloudPush(String space,String password) {",
                           "private void cloudPushConfirmed(")
        self.assertIn("if(accountsReadonly)", method)
        self.assertIn("已禁止上传", method)
        self.assertNotIn("cloudRun(", method)
        self.assertLess(method.index("if(accountsReadonly)"),
                        method.index("cloudPushConfirmed(space,password)"))

    def test_remote_upload_requires_explicit_confirmation(self):
        method = self.part("private void cloudPush(String space,String password) {",
                           "private void cloudPushConfirmed(")
        self.assertIn("setNegativeButton(\"取消\"", method)
        self.assertIn("setPositiveButton(\"确认上传\"", method)
        self.assertIn("会替换云端当前账号空间", method)
        confirmed = self.part("private void cloudPushConfirmed(",
                              "private void cloudPull(")
        self.assertLess(confirmed.index("if(accountsReadonly)"),
                        confirmed.index("cloudRun(() ->"))
        self.assertIn('body.put("expected_version",version)', confirmed)
        self.assertIn('GlacierCloudSync.encrypt(space,snapshot,password)', confirmed)

    def test_remote_download_requires_explicit_confirmation(self):
        prompt = self.part("private void cloudPull(String space,String password) {",
                           "private void cloudPullConfirmed(")
        self.assertIn("if(accountsReadonly)", prompt)
        self.assertIn("setNegativeButton(\"取消\"", prompt)
        self.assertIn("setPositiveButton(\"确认下载\"", prompt)
        self.assertNotIn("cloudRun(", prompt)
        confirmed = self.part("private void cloudPullConfirmed(",
                              "private void cloudLogout(")
        self.assertLess(confirmed.index("if(accountsReadonly)"),
                        confirmed.index("cloudRun(() ->"))
        self.assertIn("beforeDownload.equals(GlacierAutoSync.fingerprint(accountCards,space))",
                      confirmed)
        self.assertIn("persistAccountVault(merged)", confirmed)


if __name__ == "__main__":
    unittest.main()
