"""Check Windows preview discovery never falls back to GitHub or direct IP."""
import unittest
from unittest.mock import patch

from glacier_preview_updates25 import (
    ASSET_ROOT25, PREVIEW_FEED25, PreviewError25,
    select_preview25, fetch_preview25,
)


def preview(version="0.20.5"):
    return {
        "platform": "windows", "channel": "preview-manual",
        "version": version,
        "url": ASSET_ROOT25 + f"GlacierBrowser-v{version}-Windows-Setup-x64.exe",
        "size": 175_000_000,
        "sha256": "a" * 64,
    }


class VpsPreviewTests(unittest.TestCase):
    def test_new_version_and_exact_vps_asset(self):
        self.assertEqual(select_preview25(preview(), "0.20.4")["version"], "0.20.5")
        self.assertIsNone(select_preview25(preview(), "0.20.5"))
        self.assertIsNone(select_preview25(preview("0.20.3"), "0.20.4"))

    def test_rejects_github_url_and_third_party_asset(self):
        for bad in ("https://github.com/owner/repo/releases/download/app.exe",
                    "https://attacker.example/GlacierBrowser-v0.20.5-Windows-Setup-x64.exe",
                    ASSET_ROOT25 + "GlacierBrowser-v0.20.6-Windows-Setup-x64.exe"):
            data = preview()
            data["url"] = bad
            with self.assertRaises(PreviewError25):
                select_preview25(data, "0.20.4")

    def test_formal_channel_must_not_be_accepted_as_preview(self):
        for change in ({"channel": "stable"}, {"platform": "macos-arm64"},
                       {"size": 1}, {"sha256": "invalid"}, {"unexpected": 1}):
            data = dict(preview(), **change)
            with self.assertRaises(PreviewError25):
                select_preview25(data, "0.20.4")

    @patch("glacier_preview_updates25.requests.Session")
    def test_only_vps_feed_via_socks_no_direct_connection(self, factory):
        response = factory.return_value.get.return_value.__enter__.return_value
        response.status_code = 200
        response.headers = {}
        response.iter_content.return_value = [b'{"platform":"windows","channel":"preview-manual",'
                                              b'"version":"0.20.3","url":"https://sync.borealos.cn/'
                                              b'downloads/GlacierBrowser-v0.20.3-Windows-Setup-x64.exe",'
                                              b'"size":175000000,"sha256":"'
                                              + (b"a" * 64) + b'"}']
        self.assertIsNone(fetch_preview25("0.20.4", 18566))
        session = factory.return_value
        self.assertFalse(session.trust_env)
        self.assertEqual(session.proxies["https"], "socks5h://127.0.0.1:18566")
        self.assertEqual(session.get.call_args.args[0], PREVIEW_FEED25)
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])


if __name__ == "__main__":
    unittest.main()
