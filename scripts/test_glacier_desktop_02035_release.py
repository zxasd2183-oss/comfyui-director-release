"""Fail-closed static preflight for Glacier 0.20.35 native icon installers."""
import subprocess
import unittest
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/".github/workflows/glacier-desktop-02035-verified-release.yml"

class DesktopVerifiedRelease(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src=FILE.read_text(encoding="utf8")
        cls.doc=yaml.load(cls.src,Loader=yaml.BaseLoader)
        cls.job=cls.doc["jobs"]["publish-desktop"]
        cls.steps=cls.job["steps"]

    def test_pinned_native_qa_and_unpublished_source(self):
        e=self.job["env"]
        self.assertEqual(e["SOURCE_SHA"],"0a97660066764619e33a540cffdbffe968b3f658")
        self.assertEqual(e["WINDOWS_RUN"],"44861852263")
        self.assertEqual(e["MAC_RUN"],"44861852478")
        self.assertEqual(e["WIN_TAG"],"glacier-v0.20.35")
        self.assertEqual(e["MAC_TAG"],"glacier-macos-v0.20.35")
        self.assertEqual(self.doc["on"]["push"]["branches"],["main"])
        self.assertEqual(self.doc["permissions"],{"contents":"write","actions":"write"})
        self.assertIn("refs/heads/main",self.job["if"])
        self.assertIn("cancel-in-progress: false",self.src)

    def test_real_builds_and_signatures_are_pinned(self):
        for s in ("head_sha","head_branch","conclusion","build-publish","macos-arm64",
                  "git','diff','--exit-code","glacier_desktop_icons.py",
                  "GlacierBrowser-RC-Windows-Setup","GlacierBrowser-RC-macOS-AppleSilicon-DMG",
                  "b'MZ'","b'koly'","hashlib.file_digest","0.20.35"):
            self.assertIn(s,self.src)

    def test_only_original_bytes_can_be_published(self):
        names=[s.get("name","") for s in self.steps]
        def index(fragment):return next(i for i,x in enumerate(names) if fragment in x)
        for a,b in (("Pin both","Reject reused"),("Reject reused","Download only"),
                    ("Download only","Independently verify"),("Independently verify","Create two"),
                    ("Create two","Confirm exact"),("Confirm exact","Publish checked"),
                    ("Publish checked","Trigger existing")):
            self.assertLess(index(a),index(b))
        for s in ("--draft","target_commitish","RELEASE_ID","draft=false",
                  "assets[0].get('digest')","sha256:","GITHUB_SHA"):
            self.assertIn(s,self.src)
        for forbidden in ("gh release delete","gh release upload","--clobber"):
            self.assertNotIn(forbidden,self.src)

    def test_shell_syntax(self):
        for step in self.steps:
            if "run" not in step:continue
            result=subprocess.run(["bash","-n"],input=step["run"],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,step.get("name")+result.stderr[:400])

if __name__=="__main__":
    unittest.main()
