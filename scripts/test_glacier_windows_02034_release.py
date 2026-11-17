"""Fail-closed checks for Glacier Windows 0.20.34 signed-release promotion."""
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / ".github/workflows/glacier-windows-02034-verified-release.yml"


class Windows02034ReleaseSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATH.read_text(encoding="utf-8")
        cls.config = yaml.load(cls.text, Loader=yaml.BaseLoader)
        cls.job = cls.config["jobs"]["publish-windows"]

    def test_main_only_explicit_once_gate(self):
        self.assertEqual(
            self.config["on"]["push"]["branches"], ["main"])
        self.assertEqual(
            self.config["on"]["push"]["paths"],
            [".github/workflows/glacier-windows-02034-verified-release.yml"])
        self.assertEqual(self.config["permissions"], {
            "contents": "write", "actions": "write"})
        self.assertIn("github.repository ==", self.job["if"])
        self.assertIn("refs/heads/main", self.job["if"])
        self.assertIn("cancel-in-progress: false", self.text)

    def test_pin_original_verified_candidate_and_version(self):
        env = self.job["env"]
        self.assertEqual(env["SOURCE_SHA"],
                         "bb329238124baf096ac5a0bfa08d7527de36b8ae")
        self.assertEqual(env["WIN_RUN"], "44033772542")
        self.assertEqual(env["EXPECTED_TAG"], "glacier-v0.20.34")
        self.assertEqual(env["EXPECTED_INSTALLER"],
                         "GlacierBrowser-v0.20.34-Windows-Setup-x64.exe")
        for item in ("head_branch", "head_sha", "conclusion",
                     "release/glacier-min8-02034-android029-rc-20261116",
                     "git','diff','--exit-code",
                     "glacier-windows/",
                     "scripts/glacier_prepare_rotated_update.py",
                     "scripts/glacier_release_version_check.py",
                     ".github/workflows/glacier-rc-windows.yml"):
            self.assertIn(item, self.text)

    def test_verification_precedes_publication(self):
        names = [item.get("name", "") for item in self.job["steps"]]
        def index(part):
            return next(i for i, name in enumerate(names) if part in name)
        self.assertLess(index("Refuse unapproved"), index("Reject reused"))
        self.assertLess(index("Reject reused"), index("Download only"))
        self.assertLess(index("Download only"), index("Independently verify"))
        self.assertLess(index("Independently verify"), index("DRAFT release"))
        self.assertLess(index("DRAFT release"), index("Verify draft"))
        self.assertLess(index("Verify draft"), index("Publish only"))
        self.assertLess(index("Publish only"), index("Trigger existing"))
        for item in ("len(a)!=1", "a[0].get('digest')!=expected",
                     "doc.get('draft') is not True",
                     "a[0].get('size')", "b'MZ'", "hashlib.file_digest",
                     "gh release edit", "--draft=false",
                     "gh release create", "--draft",
                     "gh workflow run glacier-preview-immediate.yml",
                     "gh workflow run glacier-windows-signed-auto.yml"):
            self.assertIn(item, self.text)

    def test_all_shell_steps_parse_and_gates_stay_separate(self):
        for step in self.job["steps"]:
            if "run" not in step:
                continue
            p = subprocess.run(["bash", "-n"], input=step["run"],
                               text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, step["name"] + p.stderr[:600])
        self.assertNotIn("gh release create glacier-macos", self.text)
        self.assertNotIn("gh release create glacier-android-browser", self.text)


if __name__ == "__main__":
    unittest.main()
