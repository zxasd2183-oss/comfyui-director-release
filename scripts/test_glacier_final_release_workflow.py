"""Guard the one-shot 3-platform release workflow without publishing."""
from pathlib import Path
import unittest

SRC=(Path(__file__).resolve().parents[1]/".github/workflows/glacier-final-once.yml").read_text(encoding="utf-8")

class GlacierOneReleaseWorkflow(unittest.TestCase):
    def test_three_exact_installers_and_signed_android_source(self):
        for item in (
            '42978496121', '42978270136', '42989730306',
            'GlacierBrowser-v0.20.20-Windows-Setup-x64.exe',
            'GlacierBrowser-v0.20.17-macOS-AppleSilicon.dmg',
            'GlacierAndroid-v0.2.3-ARM64-x86_64-release.apk',
            'GlacierAndroid-v0.2.3-STABLE-SIGNED-RC-NOT-PUBLISHED',
            'GH_ANDROID_CERT_PIN', 'GLACIER_APKSIGNER', 'libxul.so', 'libsingbox.so',
            "versionCode='12'", "versionName='0.2.3'",
        ):
            self.assertIn(item, SRC)

    def test_no_public_release_before_all_drafts_verified(self):
        self.assertLess(SRC.index('Stage all three as DRAFT'),SRC.index('Validate all three exact DRAFT'))
        self.assertLess(SRC.index('Validate all three exact DRAFT'),SRC.index('Publish verified Android'))
        self.assertIn('cancel-in-progress: false',SRC)
        self.assertIn('branches: [main]',SRC)
        self.assertIn('if gh release view',SRC)
        self.assertIn("unchanged=subprocess.run(['git','diff','--quiet'",SRC)

if __name__ == "__main__":
    unittest.main()
