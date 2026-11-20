"""Regression guards for Glacier Android foreground update polling."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "glacier-android-gecko/app/src/main/java/cn/borealos/glacier/geckopreview"
class ForegroundUpdateGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = (SRC / "MainActivity.java").read_text(encoding="utf8")
        cls.updater = (SRC / "BrowserUpdater.java").read_text(encoding="utf8")
        cls.transport = (SRC / "GlacierUpdateTransport.java").read_text(encoding="utf8")
        cls.check = cls.main.split("private void maybeCheckUpdatesAtStartup()", 1)[1].split("private void showUpdatePanel()", 1)[0]

    def test_failed_fetch_cannot_block_future_attempts(self):
        self.assertIn('putLong("last_attempt", now)', self.check)
        self.assertIn("if (error != null) return;", self.check)
        self.assertLess(self.check.index("updater.check(proxyMode"), self.check.index('putLong("last_checked"'))
        self.assertIn("updateCheckInFlight = false;", self.check)
        self.assertIn("UPDATE_RETRY_MS", self.check)

    def test_poll_after_resume_and_foreground_only(self):
        self.assertIn("UPDATE_CHECK_MS = 15L * 60L * 1000L", self.main)
        self.assertIn("protected void onResume()", self.main)
        self.assertIn("updateCheckHandler.postDelayed(this, UPDATE_POLL_MS)", self.main)
        self.assertIn("UPDATE_POLL_MS = 60L * 1000L", self.main)
        self.assertIn("!updateForeground", self.check)
        self.assertIn("updateForeground = true;", self.main)
        self.assertIn("updateForeground = false;", self.main)
        self.assertIn("updateCheckHandler.removeCallbacks(updateCheckTimer)", self.main)
        self.assertIn("runtime == null", self.check)
        self.assertIn("updateCheckInFlight", self.check)

    def test_candidate_filename_is_parseable_apk_not_part(self):
        self.assertIn('new File(downloadsDir,"glacier-update-candidate.apk")', self.updater)
        self.assertNotIn('"glacier-update.apk.part"', self.updater)
        self.assertIn("validateApk(temp,release)", self.updater)
        self.assertIn("temp.renameTo(ready)", self.updater)

    def test_security_guards_remain(self):
        self.assertIn("requestInstall()", self.updater)
        self.assertIn("validateApk(file,release)", self.updater)
        self.assertIn("release.sha256", self.updater)
        self.assertIn("throughVless&&!NativeProxy.alive()", self.updater)
        self.assertIn('new InetSocketAddress("127.0.0.1",socksPort)', self.transport)
        self.assertIn("No direct-network retry", self.transport)

    def test_dismissed_version_snoozed_for_a_day(self):
        self.assertIn('"last_prompt_version"', self.check)
        self.assertIn('"last_prompt_at"', self.check)
        self.assertIn("24L * 60L * 60L * 1000L", self.check)

if __name__ == "__main__":
    unittest.main()
