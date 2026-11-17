"""Safety and provenance check for macOS 0.20.34 and Android 0.2.9."""
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT=Path(__file__).resolve().parents[1]
WF=ROOT/".github/workflows/glacier-macos-02034-android-029-verified-release.yml"


class VerifiedReleaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code=WF.read_text(encoding="utf8")
        cls.spec=yaml.load(cls.code,Loader=yaml.BaseLoader)
        cls.job=cls.spec["jobs"]["publish"]
        cls.steps=cls.job["steps"]

    def test_main_only_fixed_identity(self):
        self.assertEqual(self.spec["on"]["push"]["branches"],["main"])
        self.assertEqual(self.spec["on"]["push"]["paths"],
                         [".github/workflows/glacier-macos-02034-android-029-verified-release.yml"])
        self.assertEqual(self.spec["permissions"],{"contents":"write","actions":"write"})
        self.assertIn("refs/heads/main",self.job["if"])
        self.assertIn("cancel-in-progress: false",self.code)

    def test_exact_qa_and_android_permanent_certificate(self):
        env=self.job["env"]
        self.assertEqual(env["SOURCE_SHA"],"bb329238124baf096ac5a0bfa08d7527de36b8ae")
        self.assertEqual(env["MAC_RUN"],"44033772556")
        self.assertEqual(env["ANDROID_RUN"],"44033772660")
        self.assertEqual(env["MAC_TAG"],"glacier-macos-v0.20.34")
        self.assertEqual(env["ANDROID_TAG"],"glacier-android-browser-v0.2.9")
        self.assertEqual(env["MAC_FILE"],"GlacierBrowser-v0.20.34-macOS-AppleSilicon.dmg")
        self.assertEqual(env["ANDROID_FILE"],"GlacierAndroid-v0.2.9-ARM64-x86_64-release.apk")
        self.assertEqual(env["GLACIER_ANDROID_CERT_SHA256"],
                         "6d8fb8a4b3dd90427ff2f7959394df4b73f37c117a7d1d2e983bde0f10a1ff4e")
        for item in ("head_branch", "head_sha", "conclusion", "head_sha",
                     "glacier-macos/", "glacier-android-gecko/",
                     ".github/workflows/glacier-rc-macos.yml",
                     ".github/workflows/glacier-rc-android.yml",
                     "Build permanent-signature Android RC",
                     "Android 15 x86_64 real-APK UI smoke",
                     "Android 15 Keystore saved-node persistence M01",
                     "versionCode='18'", "versionName='0.2.9'",
                     "libxul.so", "libsingbox.so", "apksigner",
                     "Signer #1 certificate SHA-256 digest", "koly"):
            self.assertIn(item,self.code)

    def test_strict_ordering_and_immutable_draft_first(self):
        names=[s.get("name","") for s in self.steps]
        def idx(fragment):
            return next(i for i,v in enumerate(names) if fragment in v)
        for earlier,later in (
            ("Pin exact", "Refuse reused"),
            ("Refuse reused", "Download only"),
            ("Download only", "Verify full installer"),
            ("Verify full installer", "Create two nonpublic"),
            ("Create two nonpublic", "Refuse release"),
            ("Refuse release", "Publish both"),
            ("Publish both", "Ask existing"),
        ):
            self.assertLess(idx(earlier),idx(later))
        for item in ("--draft", "gh release create", "draft=false",
                     "assets[0].get('digest')", "assets[0].get('size')",
                     "doc.get('draft') is not True", "published_at",
                     "gh workflow run glacier-preview-immediate.yml",
                     "gh workflow run glacier-macos-signed-auto.yml",
                     "gh api", "git','diff','--exit-code"):
            self.assertIn(item,self.code)
        self.assertNotIn("gh release create glacier-v0.20.34",self.code)
        self.assertNotIn("gh release upload",self.code)
        self.assertNotIn("gh release delete",self.code)
        self.assertNotIn("gh workflow run glacier-windows-signed-auto.yml",self.code)

    def test_shell_steps_parse(self):
        for step in self.steps:
            if "run" not in step:
                continue
            p=subprocess.run(["bash","-n"],input=step["run"],
                             text=True,capture_output=True)
            self.assertEqual(p.returncode,0,step["name"]+" "+p.stderr[:700])


if __name__=="__main__":
    unittest.main()
