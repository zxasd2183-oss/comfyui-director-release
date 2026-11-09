"""Release-list trust boundary tests for opt-in preview discovery."""
import unittest
from unittest.mock import patch

from glacier_preview_updates25 import (
    ASSET_PREFIX, RELEASE_ROOT, PreviewError25, select_preview25,
    fetch_preview25,
)


def release(version="0.20.3", sha="abcdef0", asset=True):
    tag = f"glacier-v{version}-sync-v1-{sha}"
    name = f"GlacierBrowser-v{version}-Windows-Setup-x64.exe"
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": True,
        "html_url": RELEASE_ROOT + tag,
        "assets": ([{
            "name": name,
            "browser_download_url": ASSET_PREFIX + tag + "/" + name,
            "size": 175_000_000,
        }] if asset else []),
    }


class PreviewTrustTests(unittest.TestCase):
    def test_only_newer_preview_visible(self):
        self.assertEqual(select_preview25([release()], "0.20.2")["version"], "0.20.3")
        self.assertIsNone(select_preview25([release()], "0.20.3"))
        self.assertIsNone(select_preview25([release("0.20.1")], "0.20.2"))

    def test_unsigned_preview_cannot_become_formal_update(self):
        self.assertIsNone(select_preview25([dict(release(), prerelease=False)], "0.20.2"))
        self.assertIsNone(select_preview25([dict(release(), draft=True)], "0.20.2"))

    def test_release_page_must_be_official(self):
        self.assertIsNone(select_preview25(
            [dict(release(), html_url="https://attacker.example/release")], "0.20.2"))

    def test_assets_must_match_exact_tag_and_version(self):
        base = release()
        base["assets"][0]["browser_download_url"] = "https://attacker.example/setup.exe"
        self.assertIsNone(select_preview25([base], "0.20.2"))
        missing = release(asset=False)
        self.assertIsNone(select_preview25([missing], "0.20.2"))

    def test_malformed_listing_rejected(self):
        with self.assertRaises(PreviewError25):
            select_preview25({}, "0.20.2")

    @patch("glacier_preview_updates25.requests.Session")
    def test_request_must_use_local_socks_only(self, factory):
        response = factory.return_value.get.return_value.__enter__.return_value
        response.status_code = 200
        response.headers = {"Content-Length": "2"}
        response.iter_content.return_value = [b"[]"]
        self.assertIsNone(fetch_preview25("0.20.2", 18566))
        session = factory.return_value
        self.assertFalse(session.trust_env)
        self.assertEqual(session.proxies["https"], "socks5h://127.0.0.1:18566")
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])


if __name__ == "__main__":
    unittest.main()
