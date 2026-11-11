"""No Android SDK required: check real inputs and detect stale version references."""
import tempfile
import unittest
from pathlib import Path

from check_rc_version_consistency import inspect


class TestRcVersionConsistency(unittest.TestCase):
    @staticmethod
    def source_root():
        return Path(__file__).resolve().parents[2]

    def test_real_checkout(self):
        self.assertEqual(inspect(self.source_root()), "0.2.3")

    def test_stale_instrumentation_script_blocks_before_emulator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "glacier-android-gecko/app"
            scripts = root / "glacier-android-gecko/scripts"
            wf = root / ".github/workflows"
            app.mkdir(parents=True)
            scripts.mkdir(parents=True)
            wf.mkdir(parents=True)
            (app / "build.gradle").write_text("versionCode 12\nversionName '0.2.3'\n")
            expected = "GlacierAndroid-v0.2.3-Mobile-M05-ARM64-x86_64-debug.apk"
            (scripts / "run_saved_vless_test.sh").write_text(expected)
            (scripts / "run_emulator_smoke.sh").write_text(expected)
            (wf / "glacier-rc-android.yml").write_text(expected)
            self.assertEqual(inspect(root), "0.2.3")
            (scripts / "run_saved_vless_test.sh").write_text(expected.replace("0.2.3", "0.2.2"))
            with self.assertRaisesRegex(ValueError, "does not reference"):
                inspect(root)


if __name__ == "__main__":
    unittest.main()
