"""Fail-closed safety checks for resuming original Glacier 0.20.35 drafts."""
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/glacier-desktop-02035-resume-verified-drafts.yml"

class DraftResumeGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src=WORKFLOW.read_text(encoding="utf8")
        cls.doc=yaml.load(cls.src,Loader=yaml.BaseLoader)
        cls.job=cls.doc["jobs"]["resume-publish"]

    def test_exact_original_release_ids_and_sha_are_pinned(self):
        e=self.job["env"]
        self.assertEqual(e["SOURCE_SHA"],"0a97660066764619e33a540cffdbffe968b3f658")
        self.assertEqual(e["ORIGINAL_PUBLISH_SHA"],"76aa51baec87f8b6e60dca7ca1d7e555646aa2c4")
        self.assertEqual(e["WIN_RELEASE_ID"],"453416459")
        self.assertEqual(e["MAC_RELEASE_ID"],"453416500")
        self.assertEqual(e["WIN_SHA256"],"d90c43d727f0dad3e89eb97af7b4e1ae5b6df1ddb8cbd2dac04f5eb4894a724e")
        self.assertEqual(e["MAC_SHA256"],"181e8ca08295336eff5313675642f3d1407df198ecedc7284cf1d19fda61121c")

    def test_no_new_release_upload_or_unsafe_mutation(self):
        for needed in ("head_sha","head_branch","git','diff','--exit-code",
                       "releases?per_page=100","releases/{rid}",
                       "digest","uploaded","draft=false","published_at",
                       "GLACIER","glacier-preview-immediate"):
            if needed!="GLACIER":self.assertIn(needed,self.src)
        for bad in ("gh release delete","gh release upload","gh release create","--clobber"):
            self.assertNotIn(bad,self.src)
        self.assertIn("cancel-in-progress: false",self.src)
        self.assertIn("refs/heads/main",self.job["if"])

    def test_bash_syntax(self):
        for step in self.job["steps"]:
            if "run" not in step:continue
            result=subprocess.run(["bash","-n"],input=step["run"],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,step.get("name","")+result.stderr[:300])

if __name__=="__main__":
    unittest.main()
