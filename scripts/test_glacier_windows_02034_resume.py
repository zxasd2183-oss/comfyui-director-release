"""Ensure a failed Glacier draft is resumed by immutable ID with no new upload."""
import subprocess
import unittest
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]
WF=ROOT/".github/workflows/glacier-windows-02034-resume-draft.yml"


class TestWindowsDraftResume(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=WF.read_text(encoding='utf8')
        cls.spec=yaml.load(cls.text,Loader=yaml.BaseLoader)
        cls.job=cls.spec['jobs']['resume']

    def test_main_only_immutable_draft(self):
        self.assertEqual(cls_on(self.spec)['push']['branches'],['main'])
        self.assertEqual(cls_on(self.spec)['push']['paths'],
                         ['.github/workflows/glacier-windows-02034-resume-draft.yml'])
        self.assertEqual(self.spec['permissions'],{'contents':'write','actions':'write'})
        self.assertIn('refs/heads/main',self.job['if'])
        self.assertIn('cancel-in-progress: false',self.text)

    def test_pins_verified_old_draft_and_sha256(self):
        env=self.job['env']
        self.assertEqual(env['RELEASE_ID'],'448290367')
        self.assertEqual(env['WIN_RUN'],'44033772542')
        self.assertEqual(env['SOURCE_SHA'],'bb329238124baf096ac5a0bfa08d7527de36b8ae')
        self.assertEqual(env['ORIGINAL_PROMOTION_SHA'],'05b76f4e968a4660ff4d5affe79200deab1b1399')
        self.assertEqual(env['RELEASE_SIZE'],'175970856')
        self.assertEqual(env['RELEASE_DIGEST'],
                         '7954c7551d43446b6c6acffd9b07d90bb4bf086aa44e351f288bd26aeacbcb5f')
        self.assertEqual(env['RELEASE_TAG'],'glacier-v0.20.34')

    def test_only_publish_original_if_unmodified(self):
        steps=[s.get('name','') for s in self.job['steps']]
        def i(text):
            return next(pos for pos,s in enumerate(steps) if text in s)
        self.assertLess(i('Verify original'),i('Verify exact'))
        self.assertLess(i('Verify exact'),i('Publish exact'))
        self.assertLess(i('Publish exact'),i('Request existing'))
        for phrase in ('gh api -X PATCH', '-F draft=false', 'releases/$RELEASE_ID',
                       "get('draft') is not True",
                       "get('digest')!='sha256:'",
                       "get('state')!='uploaded'",
                       "get('size')!=int(os.environ['RELEASE_SIZE'])",
                       'gh workflow run glacier-preview-immediate.yml',
                       'gh workflow run glacier-windows-signed-auto.yml'):
            self.assertIn(phrase,self.text)
        self.assertNotIn('gh release create',self.text)
        self.assertNotIn('gh release upload',self.text)
        self.assertNotIn('gh release delete',self.text)

    def test_shell_syntax(self):
        for step in self.job['steps']:
            if 'run' not in step:continue
            p=subprocess.run(['bash','-n'],input=step['run'],
                             text=True,capture_output=True)
            self.assertEqual(p.returncode,0,step['name']+p.stderr[:400])


def cls_on(spec):
    return spec['on']


if __name__ == '__main__':
    unittest.main()
