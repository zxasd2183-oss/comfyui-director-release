"""Regression safety gate for Glacier's three-platform rollback-guard release."""
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/glacier-v032-android027-verified-release.yml"

class BackupGuardReleaseSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=WORKFLOW.read_text(encoding="utf-8")
        cls.config=yaml.load(cls.source,Loader=yaml.BaseLoader)
        cls.job=cls.config["jobs"]["release"]

    def test_trusted_once_only_main_path_permissions(self):
        self.assertEqual(self.config["on"]["push"]["branches"],["main"])
        self.assertEqual(self.config["on"]["push"]["paths"],[
            ".github/workflows/glacier-v032-android027-verified-release.yml"])
        self.assertEqual(self.config["permissions"]["contents"],"write")
        self.assertEqual(self.config["permissions"]["actions"],"write")
        self.assertIn("refs/heads/main",self.job["if"])

    def test_original_native_source_and_all_emulator_gates(self):
        environment=self.job["env"]
        self.assertEqual(environment["WIN_RUN"],"43830191635")
        self.assertEqual(environment["MAC_RUN"],"43830191628")
        self.assertEqual(environment["ANDROID_RUN"],"43830191692")
        self.assertEqual(environment["SOURCE_SHA"],
                         "3c4227842082910688280d7ba7e5393d14f3e8c7")
        for text in ("head_sha","head_branch","conclusion",
                     "Build permanent-signature Android RC",
                     "Android 15 x86_64 real-APK UI smoke",
                     "Android 15 Keystore saved-node persistence",
                     "scripts/glacier_prepare_rotated_update.py"):
            self.assertIn(text,self.source)

    def test_complete_sha256_signatures_and_draft_before_public(self):
        for item in ("GlacierBrowser-v0.20.32-Windows-Setup-x64.exe",
                     "GlacierBrowser-v0.20.32-macOS-AppleSilicon.dmg",
                     "GlacierAndroid-v0.2.7-ARM64-x86_64-release.apk",
                     "versionCode='16'","versionName='0.2.7'",
                     "apksigner","libxul.so","libsingbox.so",
                     "sha256","digest","koly"):
            self.assertIn(item,self.source)
        steps=[s.get("name","") for s in self.job["steps"]]
        def seq(k):
            return next(i for i,s in enumerate(steps) if k in s)
        self.assertLess(seq("Prove all original"),seq("Refuse any previously"))
        self.assertLess(seq("Refuse any previously"),seq("Download only full"))
        self.assertLess(seq("Download only full"),seq("Independently verify"))
        self.assertLess(seq("Independently verify"),seq("Stage all three"))
        self.assertLess(seq("Stage all three"),seq("Validate all three DRAFT"))
        self.assertLess(seq("Validate all three DRAFT"),seq("Publish only"))
        self.assertLess(seq("Publish only"),seq("Request Glacier-only"))
        self.assertIn("doc.get('draft') is not True",self.source)
        self.assertIn("repos/{repo}/releases?per_page=100",self.source)
        self.assertIn("gh workflow run glacier-preview-immediate.yml",self.source)

    def test_all_shell_steps_parse(self):
        for step in self.job["steps"]:
            if "run" not in step: continue
            proc=subprocess.run(["bash","-n"],input=step["run"],
                               text=True,capture_output=True)
            self.assertEqual(proc.returncode,0,
                step.get("name","")+" "+proc.stderr[:500])

if __name__=="__main__":
    unittest.main()
