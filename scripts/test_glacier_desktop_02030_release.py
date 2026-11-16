"""Glacier browser 0.20.30 immutable Windows/macOS release safety checks."""
import subprocess
import unittest
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/".github/workflows/glacier-desktop-02030-verified-release.yml"

class VerifiedDesktopRelease(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=SOURCE.read_text(encoding="utf-8")
        cls.data=yaml.load(cls.raw,Loader=yaml.BaseLoader)
        cls.job=cls.data["jobs"]["verify-and-publish"]

    def test_trigger_is_explicit_trusted_main_file(self):
        self.assertEqual(self.data["on"]["push"]["branches"],["main"])
        self.assertEqual(self.data["on"]["push"]["paths"],[
            ".github/workflows/glacier-desktop-02030-verified-release.yml"])
        self.assertEqual(self.data["permissions"]["contents"],"write")
        self.assertEqual(self.data["permissions"]["actions"],"write")
        self.assertIn("refs/heads/main",self.job["if"])
        self.assertEqual(self.job["env"]["BUILD_SHA"],
                         "9ff07479d469683284d74667cb82645495744f6f")

    def test_two_exact_native_successful_runs(self):
        raw=self.raw
        for fragment in ("43807437745","43807437703",
                         "j.get('conclusion')!='success'",
                         "j.get('head_sha')!=sha",
                         "git','diff','--exit-code",
                         "scripts/glacier_prepare_rotated_update.py"):
            self.assertIn(fragment,raw)
        self.assertNotIn("glacier-android-browser",raw)
        self.assertNotIn("Director",raw)

    def test_draft_first_sha256_check_before_publication(self):
        steps=self.job["steps"]
        names=[s.get("name","") for s in steps]
        def index(substr):
            return next(i for i,name in enumerate(names) if substr in name)
        self.assertLess(index("Require successful"),index("Refuse existing"))
        self.assertLess(index("Refuse existing"),index("Download exact"))
        self.assertLess(index("Download exact"),index("Verify entire"))
        self.assertLess(index("Verify entire"),index("Stage both"))
        self.assertLess(index("Stage both"),index("Verify exactly both"))
        self.assertLess(index("Verify exactly both"),index("Publish only"))
        self.assertLess(index("Publish only"),index("Dispatch Glacier-only"))
        self.assertEqual(self.raw.count(" --draft \\"),2)
        self.assertIn("doc.get('draft') is not True",self.raw)
        self.assertIn("hashlib.file_digest(source,'sha256')",self.raw)
        self.assertIn("repos/{repo}/releases?per_page=100",self.raw)
        self.assertIn("gh workflow run glacier-preview-immediate.yml",self.raw)

    def test_only_new_expected_versions_and_offline_installer_artifacts(self):
        self.assertIn("glacier-v0.20.30",self.raw)
        self.assertIn("glacier-macos-v0.20.30",self.raw)
        self.assertIn("GlacierBrowser-v0.20.30-Windows-Setup-x64.exe",self.raw)
        self.assertIn("GlacierBrowser-v0.20.30-macOS-AppleSilicon.dmg",self.raw)
        for bad in ("glacier-v0.20.29","glacier-macos-v0.20.29",
                    "GlacierAndroid", "curl -X", "sync.borealos.cn:"):
            self.assertNotIn(bad,self.raw)

    def test_all_shell_steps_parse(self):
        for step in self.job["steps"]:
            script=step.get("run")
            if script is None:
                continue
            result=subprocess.run(["bash","-n"],input=script,
                                  text=True,capture_output=True,check=False)
            self.assertEqual(result.returncode,0,
                             step.get("name","")+" "+result.stderr[:1000])

if __name__=="__main__":
    unittest.main()
