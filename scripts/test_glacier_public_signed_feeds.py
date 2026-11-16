"""Pure, network-free tests of Glacier's public update feed acceptance rules."""
import base64
import unittest

from glacier_verify_public_signed_feeds import (
    latest_release, validate_feed, version_tuple, VPS, KEY_ID
)


class PublicSignedFeedTests(unittest.TestCase):
    def setUp(self):
        self.version = "0.20.32"
        self.name = "GlacierBrowser-v0.20.32-Windows-Setup-x64.exe"
        self.release = {"tag_name": "glacier-v0.20.32", "draft": False,
                        "prerelease": False,
                        "published_at": "2026-11-16T08:29:34Z",
                        "assets": [{"name": self.name, "size": 12345,
                                    "digest": "sha256:" + "a" * 64}]}
        self.feed = {"channel": "windows-x64", "key_id": KEY_ID,
                     "version": self.version, "size": 12345,
                     "sha256": "a" * 64, "url": VPS + self.name,
                     "signature": base64.b64encode(b"x" * 64).decode("ascii")}

    def test_good_official_manifest_is_accepted(self):
        self.assertEqual(validate_feed("windows-x64", self.version,
              self.release, "Windows-Setup-x64.exe",
              self.feed, dict(self.feed)), "a" * 64)

    def test_stale_or_tampered_live_feed_is_rejected(self):
        for field, value in (("version", "0.20.31"), ("size", 12344),
                             ("url", "https://evil.example.invalid/"),
                             ("sha256", "b" * 64)):
            with self.subTest(field=field):
                tampered = dict(self.feed, **{field: value})
                with self.assertRaises(RuntimeError):
                    validate_feed("windows-x64", self.version, self.release,
                                  "Windows-Setup-x64.exe", self.feed, tampered)

    def test_reject_bad_signer_identity_and_asset_mismatch(self):
        for changed in ({"key_id": "other"}, {"signature": ""},
                        {"size": 999}, {"sha256": "b" * 64},
                        {"url": VPS + "wrong.exe"}):
            with self.subTest(changed=changed):
                feed = dict(self.feed, **changed)
                with self.assertRaises(RuntimeError):
                    validate_feed("windows-x64", self.version, self.release,
                                  "Windows-Setup-x64.exe", feed, feed)

    def test_latest_release_ignores_drafts_and_old_versions(self):
        older = dict(self.release, tag_name="glacier-v0.20.31")
        draft = dict(self.release, tag_name="glacier-v0.20.99", draft=True)
        latest, item = latest_release([older, draft, self.release], "glacier-v")
        self.assertEqual(latest, self.version)
        self.assertIs(item, self.release)

    def test_version_parser_rejects_noncanonical_values(self):
        self.assertEqual(version_tuple("0.20.32"), (0, 20, 32))
        for version in ("0.020.32", "0.20.32-beta", "0.20", "0.20.32.1"):
            with self.assertRaises(RuntimeError):
                version_tuple(version)


if __name__ == "__main__":
    unittest.main()
