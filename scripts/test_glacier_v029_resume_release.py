"""Safety check for Glacier v0.20.29/Android v0.2.4 draft-only publication resume."""
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / ".github/workflows/glacier-v029-publish-existing-drafts.yml"

class ResumeSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src=PATH.read_text(encoding="utf-8")
        cls.config=yaml.load(cls.src, Loader=yaml.BaseLoader)
        cls.job=cls.config["jobs"]["release-existing-verified-drafts"]

    def test_only_single_trusted_main_push_and_minimum_permissions(self):
        self.assertEqual(self.config["on"]["push"]["branches"], ["main"])
        self.assertEqual(self.config["on"]["push"]["paths"], [
            ".github/workflows/glacier-v029-publish-existing-drafts.yml"])
        self.assertEqual(self.config["permissions"]["contents"], "write")
        self.assertEqual(self.config["permissions"]["actions"], "write")
        self.assertIn("refs/heads/main",self.job["if"])
        self.assertEqual(self.job["env"]["BUILD_SHA"],
                         "876465cad539eb6f688a9c70f987669c6e38c479")

    def test_pristine_provenance_and_no_new_draft_upload(self):
        src=self.src
        self.assertIn("43791661384/jobs?per_page=100",src)
        for run in ("43790619983","43790619985","43790619947"):
            self.assertIn(run,src)
        self.assertIn("Verify 3 complete installer files and Android fixed certificate/ABI",src)
        self.assertIn('result.get("head_sha")!=sha',src)
        self.assertIn('"glacier-windows/","glacier-macos/"',src)
        self.assertIn('item.get("draft") is not True',src)
        self.assertNotIn("gh release create",src)
        self.assertNotIn("--upload",src)

    def test_draft_ids_asset_digests_and_publish_order(self):
        for value in ("446538402","446538464","446538545",
                      "7477b2952c604722957fb6ef0f93621b3f5ca2ec912fa2cc85c310588dac23d4",
                      "3979a622fc6964f5184ac013a5ab5618503be61b48e18985dea74977f329d993",
                      "2bf15dd7e85f9f74e781401e26723e694bc4ba6d01426a989fa6ad81babf53d4"):
            self.assertIn(value,self.src)
        self.assertEqual(self.src.count("-F draft=false"),1)
        self.assertIn("gh workflow run glacier-preview-immediate.yml",self.src)
        self.assertIn("Original verified full-byte SHA256",self.src)
        steps=self.job["steps"]
        labels=[s.get("name","") for s in steps]
        self.assertLess(next(i for i,s in enumerate(labels) if "Prove all three" in s),
                        next(i for i,s in enumerate(labels) if "Validate exactly" in s))
        self.assertLess(next(i for i,s in enumerate(labels) if "Validate exactly" in s),
                        next(i for i,s in enumerate(labels) if "Publish only" in s))
        self.assertLess(next(i for i,s in enumerate(labels) if "Publish only" in s),
                        next(i for i,s in enumerate(labels) if "Dispatch existing" in s))

    def test_embedded_bash_scripts_have_valid_syntax(self):
        for step in self.job["steps"]:
            script=step.get("run")
            if not script:
                continue
            check=subprocess.run(["bash","-n"],input=script,text=True,capture_output=True)
            self.assertEqual(check.returncode,0,
                             step.get("name","")+" "+check.stderr)

if __name__ == "__main__":
    unittest.main()
