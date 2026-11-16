"""Static guards plus instrumented Android tests for E2E cloud rollback handling."""
from pathlib import Path
import unittest

BASE=Path(__file__).resolve().parents[1]
JAVA=BASE/"app/src/main/java/cn/borealos/glacier/geckopreview"


class AndroidSyncRollbackSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sync=(JAVA/"GlacierAutoSync.java").read_text(encoding="utf-8")
        cls.ui=(JAVA/"MainActivity.java").read_text(encoding="utf-8")

    def test_old_remote_version_fails_before_local_mutation_or_upload(self):
        source=self.sync
        self.assertIn('if(versionRollsBack(before,remoteVersion))',source)
        self.assertIn('return new Result(space,"rollback",before,current,null);',source)
        self.assertLess(source.index('if(versionRollsBack(before,remoteVersion))'),
                        source.index('if(changedHere)'))
        self.assertLess(source.index('if(versionRollsBack(before,remoteVersion))'),
                        source.index('GlacierCloudSync.decrypt('))
        self.assertIn('remoteVersion=serverVersion(remote)',source)
        self.assertIn('written=serverVersion(result)',source)
        self.assertIn('if(written <= before)',source)

    def test_versions_are_strict_integers(self):
        src=self.sync
        self.assertIn('value instanceof Integer',src)
        self.assertIn('value instanceof Long',src)
        self.assertIn('observed > Integer.MAX_VALUE',src)
        self.assertIn('observed < known',src)

    def test_corrupt_response_has_visible_warning_but_no_secret_logs(self):
        self.assertIn('"rollback".equals(event.kind)',self.ui)
        self.assertIn('云端账号版本回退或响应异常',self.ui)
        self.assertNotIn('android.util.Log',self.sync)


if __name__ == "__main__":
    unittest.main()
