import unittest
import copy
from secure_update import (parse_manifest, UpdateError, newer_than, CURRENT_VERSION)

FIXTURE = {"channel":"windows-x64","version":"0.11.0","url":"https://github.com/zxasd2183-oss/comfyui-director-release/releases/download/glacier-v0.11.0/GlacierBrowser-v0.11.0-Windows-Setup-x64.exe","sha256":"0000000000000000000000000000000000000000000000000000000000000000","size":170630680,"notes":"signed updater test vector","key_id":"cf9452226375ff7d","signature":"EE+XY2Vok8xdeN3tdAxDxxbH+mC3Ch6ZB4QhUKPdvYBQKidcGFtIyd0iuWDkyDDqWFHEjOPrPxfluPmjzDJABA=="}

class GlacierUpdateSecurityTests(unittest.TestCase):
    def test_signed_manifest_accepted(self):
        self.assertEqual(parse_manifest(FIXTURE).version, '0.11.0')
    def test_checksum_tamper_rejected(self):
        altered = copy.deepcopy(FIXTURE)
        altered['sha256'] = '1' * 64
        with self.assertRaises(UpdateError): parse_manifest(altered)
    def test_version_tamper_rejected(self):
        altered = copy.deepcopy(FIXTURE)
        altered['version'] = '0.11.1'
        with self.assertRaises(UpdateError): parse_manifest(altered)
    def test_unsigned_manifest_rejected(self):
        altered = copy.deepcopy(FIXTURE)
        altered.pop('signature')
        with self.assertRaises(UpdateError): parse_manifest(altered)
    def test_different_key_rejected(self):
        altered = copy.deepcopy(FIXTURE)
        altered['key_id'] = 'foreign'
        with self.assertRaises(UpdateError): parse_manifest(altered)
    def test_signed_rollback_is_not_newer(self):
        self.assertFalse(newer_than(CURRENT_VERSION, '0.10.1'))
        self.assertTrue(newer_than('0.10.1', CURRENT_VERSION))
    def test_url_redirect_replacement_rejected(self):
        altered = copy.deepcopy(FIXTURE)
        altered['url'] = 'https://evil.example/setup.exe'
        with self.assertRaises(UpdateError): parse_manifest(altered)

if __name__ == '__main__':
    unittest.main()
