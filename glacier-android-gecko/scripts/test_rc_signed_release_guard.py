"""Offline static regression against accidental Android signed-RC bypass."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github/workflows/glacier-rc-android.yml"

class SignedReleaseGuard(unittest.TestCase):
    def test_signing_requires_six_green_android_jobs(self):
        s = CI.read_text(encoding="utf-8")
        self.assertIn("needs: [build, signing_preflight, emulator_saved_node, emulator_smoke, emulator_external_websites, emulator_proxy_fail_closed, emulator_proxy_mock_route]", s)
        self.assertIn("if: needs.signing_preflight.outputs.ready == 'true'", s)

    def test_signed_apk_must_have_correct_certificate_package_and_native_binaries(self):
        s = CI.read_text(encoding="utf-8")
        job = s.split("  signed_release_candidate:", 1)[1]
        for expected in (
            "GLACIER_ANDROID_CERT_SHA256", "apksigner",
            "cn.borealos.glacier.geckopreview", "versionCode='12'",
            "versionName='0.2.3'", "libxul.so", "libsingbox.so",
            "arm64-v8a", "x86_64",
        ):
            self.assertIn(expected, job)
        self.assertNotIn("gh release create", job)
        self.assertNotIn("contents: write", job)
        self.assertIn("STABLE-SIGNED-RC-NOT-PUBLISHED", job)

if __name__ == "__main__":
    unittest.main()
