"""Static fail-closed safety gate for Android 0.2.11 verified release."""
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/glacier-android-0211-updater-verified-release.yml"


class VerifiedUpdaterReleaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=WORKFLOW.read_text(encoding='utf8')
        cls.doc=yaml.load(cls.source,Loader=yaml.BaseLoader)
        cls.job=cls.doc["jobs"]["verified-android"]
        cls.steps=cls.job["steps"]

    def test_main_only_and_locked_down(self):
        self.assertEqual(self.doc["on"]["push"]["branches"],["main"])
        self.assertEqual(self.doc["on"]["push"]["paths"],
                [".github/workflows/glacier-android-0211-updater-verified-release.yml"])
        self.assertEqual(self.doc["permissions"],{"contents":"write","actions":"read"})
        self.assertIn("refs/heads/main",self.job["if"])
        self.assertIn("doc.get('head_branch')=='main'",self.source)
        self.assertIn("cancel-in-progress: false",self.source)

    def test_exact_native_qa_artifact_and_upgrade_certificate(self):
        env=self.job["env"]
        self.assertEqual(env["SOURCE_SHA"],"e28b967f5301a5b81c3df16dcdbeaad94fef9759")
        self.assertEqual(env["ANDROID_RUN"],"44662044870")
        self.assertEqual(env["TAG"],"glacier-android-browser-v0.2.11")
        self.assertEqual(env["APK"],"GlacierAndroid-v0.2.11-ARM64-x86_64-release.apk")
        self.assertEqual(env["GLACIER_ANDROID_CERT_SHA256"],
                "6d8fb8a4b3dd90427ff2f7959394df4b73f37c117a7d1d2e983bde0f10a1ff4e")
        for needle in ("head_branch","head_sha","conclusion",
                       "Build permanent-signature Android RC",
                       "Android 15 x86_64 real-APK UI smoke",
                       "Android 15 Keystore saved-node persistence",
                       "scripts.test_glacier_android_profile_avatar",
                       "scripts.test_glacier_android_auto_update",
                       "versionCode='20'","versionName='0.2.11'",
                       "libxul.so","libsingbox.so","apksigner",
                       "Signer #1 certificate SHA-256 digest"):
            self.assertIn(needle,self.source)

    def test_sha256_draft_guards_precede_publish_and_no_overwrites(self):
        names=[step.get("name","") for step in self.steps]
        def index(fragment):
            return next(i for i,x in enumerate(names) if fragment in x)
        for x,y in (("Verify original","Refuse existing"),
                    ("Refuse existing","Download only"),
                    ("Download only","Verify whole"),
                    ("Verify whole","Upload only"),
                    ("Upload only","Confirm private"),
                    ("Confirm private","Publish exact")):
            self.assertLess(index(x),index(y))
        for needle in ("hashlib.file_digest", "a[0].get('digest')",
                       "a[0].get('size')", "a[0].get('state')",
                       "d.get('draft') is not True",
                       "gh release create", "--draft",
                       "'PATCH'", "'draft=false'"):
            self.assertIn(needle,self.source)
        self.assertNotIn("gh release delete",self.source)
        self.assertNotIn("gh release upload",self.source)
        self.assertNotIn("glacier-v0.20.34",self.source)
        self.assertNotIn("gh workflow run glacier-preview-immediate",self.source)

    def test_shell_syntax(self):
        for step in self.steps:
            if 'run' not in step:continue
            result=subprocess.run(["bash","-n"],input=step["run"],
                                  capture_output=True,text=True)
            self.assertEqual(result.returncode,0,step.get("name","")+result.stderr[:600])


if __name__=="__main__":
    unittest.main()
