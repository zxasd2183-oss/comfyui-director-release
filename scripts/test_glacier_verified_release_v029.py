"""Offline safety preflight for the one-time Glacier v0.20.29 / Android v0.2.4 release."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / ".github/workflows/glacier-verified-v029-android024-release.yml"

class ReleaseWorkflowSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = FILE.read_text(encoding="utf-8")
        cls.config = yaml.load(cls.source, Loader=yaml.BaseLoader)

    def test_trigger_is_single_file_on_trusted_main(self):
        workflow = self.config
        self.assertEqual(workflow["on"]["push"]["branches"], ["main"])
        self.assertEqual(workflow["on"]["push"]["paths"], [
            ".github/workflows/glacier-verified-v029-android024-release.yml"
        ])
        self.assertEqual(workflow["permissions"]["contents"], "write")
        self.assertEqual(workflow["permissions"]["actions"], "write")
        self.assertEqual(workflow["concurrency"]["cancel-in-progress"], "false")
        job = workflow["jobs"]["one-final-release"]
        self.assertIn("refs/heads/main", job["if"])
        self.assertIn("zxasd2183-oss/comfyui-director-release", job["if"])

    def test_pinned_successful_three_platform_qa_inputs(self):
        job = self.config["jobs"]["one-final-release"]
        self.assertEqual(job["env"]["WINDOWS_RUN"], "43790619983")
        self.assertEqual(job["env"]["MAC_RUN"], "43790619985")
        self.assertEqual(job["env"]["ANDROID_RUN"], "43790619947")
        self.assertEqual(job["env"]["BUILD_SHA"],
                         "876465cad539eb6f688a9c70f987669c6e38c479")
        body = self.source
        self.assertIn("doc.get('conclusion')!='success'", body)
        self.assertIn("doc.get('head_sha')!=os.environ['BUILD_SHA']", body)
        self.assertIn("'git','diff','--quiet',sha,'HEAD','--',client", body)
        self.assertIn("Android production signing certificate pin changed", body)

    def test_release_gates_precede_any_publication(self):
        steps = self.config["jobs"]["one-final-release"]["steps"]
        names = [s.get("name", "") for s in steps]
        find = lambda text: next(i for i, name in enumerate(names) if text in name)
        self.assertLess(find("Require 3 successful"), find("Enforce NEVER reusing"))
        self.assertLess(find("Enforce NEVER reusing"), find("Download only"))
        self.assertLess(find("Download only"), find("Verify 3 complete"))
        self.assertLess(find("Verify 3 complete"), find("Stage all three as DRAFT"))
        self.assertLess(find("Stage all three as DRAFT"), find("Validate all three exact DRAFT"))
        self.assertLess(find("Validate all three exact DRAFT"), find("Publish verified"))
        self.assertLess(find("Publish verified"), find("Dispatch existing Glacier-only"))
        self.assertEqual(self.source.count("--target \"$BUILD_SHA\" --draft"), 3)
        self.assertEqual(self.source.count("--draft=false"), 3)
        self.assertIn("gh workflow run glacier-preview-immediate.yml", self.source)
        self.assertIn("asset.get('digest')!='sha256:'+digest", self.source)
        self.assertIn("apksigner", self.source)
        self.assertIn("GLACIER_ANDROID_CERT_SHA256", self.source)

    def test_immutable_versions_and_signed_apk_never_debug(self):
        for tag in ("glacier-v0.20.29", "glacier-macos-v0.20.29",
                    "glacier-android-browser-v0.2.4"):
            self.assertIn(tag, self.source)
        for name in ("GlacierBrowser-v0.20.29-Windows-Setup-x64.exe",
                     "GlacierBrowser-v0.20.29-macOS-AppleSilicon.dmg",
                     "GlacierAndroid-v0.2.4-ARM64-x86_64-release.apk"):
            self.assertIn(name, self.source)
        self.assertIn("GlacierAndroid-v0.2.4-STABLE-SIGNED-RC-NOT-PUBLISHED",
                      self.source)
        self.assertIn("\"versionCode='13'\"", self.source)
        self.assertIn("\"versionName='0.2.4'\"", self.source)
        for old in ("glacier-v0.20.20", "glacier-macos-v0.20.17",
                    "glacier-android-browser-v0.2.3"):
            self.assertNotIn(old, self.source)

if __name__ == "__main__":
    unittest.main()
