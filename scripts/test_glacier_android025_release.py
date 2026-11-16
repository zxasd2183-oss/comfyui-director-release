"""Offline preflight for one-time Glacier Android v0.2.5 signed APK publication."""
from pathlib import Path
import subprocess
import unittest
import yaml

FILE=Path(__file__).resolve().parents[1]/".github/workflows/glacier-android025-verified-release.yml"

class AndroidReleasePreflight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=FILE.read_text(encoding="utf-8")
        cls.workflow=yaml.load(cls.text,Loader=yaml.BaseLoader)
        cls.job=cls.workflow["jobs"]["release"]

    def test_single_file_trusted_main_only(self):
        w=self.workflow
        self.assertEqual(w["on"]["push"]["branches"],["main"])
        self.assertEqual(w["on"]["push"]["paths"],[
            ".github/workflows/glacier-android025-verified-release.yml"])
        self.assertEqual(w["permissions"]["contents"],"write")
        self.assertIn("refs/heads/main",self.job["if"])

    def test_unique_pinned_native_run_and_original_signer(self):
        self.assertEqual(self.job["env"]["QA_RUN"],"43810167937")
        self.assertEqual(self.job["env"]["BUILD_SHA"],
                         "afd2284d776a9bc106f39596667803e89a6966fc")
        self.assertIn("Android 15 x86_64 real-APK UI smoke",self.text)
        self.assertIn("Build permanent-signature Android RC",self.text)
        self.assertIn("glacier-android-gecko/",self.text)
        for t in ("versionCode='14'","versionName='0.2.5'",
                  "libxul.so","libsingbox.so","apksigner",
                  "Signer #1 certificate SHA-256 digest"):
            self.assertIn(t,self.text)

    def test_draft_then_full_hash_before_publish(self):
        steps=self.job["steps"]
        titles=[s.get("name","") for s in steps]
        self.assertLess(titles.index("Create hidden DRAFT release with verified APK"),
                        titles.index("Check unique hidden draft full SHA256 before public visibility"))
        self.assertLess(titles.index("Check unique hidden draft full SHA256 before public visibility"),
                        titles.index("Publish only verified Android permanent-signed v0.2.5 APK"))
        self.assertIn("hashlib.file_digest(stream,'sha256')",self.text)
        self.assertIn("repos/{repo}/releases?per_page=100",self.text)
        self.assertNotIn("glacier-v0.20.30",self.text)
        self.assertNotIn("glacier-macos-v0.20.30",self.text)

    def test_shell_steps_are_valid(self):
        for step in self.job["steps"]:
            if "run" in step:
                r=subprocess.run(["bash","-n"],input=step["run"],text=True,
                                 capture_output=True,check=False)
                self.assertEqual(r.returncode,0,
                    step.get("name","")+" "+r.stderr[:800])
