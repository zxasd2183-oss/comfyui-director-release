"""Offline release-mirror security gates; never download a production asset."""
import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).with_name("sync-glacier-preview-releases.py")
spec = importlib.util.spec_from_file_location("glacier_preview_mirror", SCRIPT)
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)


def release(platform="windows", version="0.20.4", sha="abcdef0"):
    tagbase = "glacier" if platform == "windows" else "glacier-macos"
    tag = (f"glacier-v{version}-sync-v1-{sha}" if platform == "windows"
           else f"glacier-macos-v{version}-sync-v1-{sha}")
    name = mirror.FILENAME[platform].format(version)
    assets = []
    for suffix, size in (("", 175_000_000), (".sha256", 112)):
        filename = name + suffix
        assets.append({"name": filename, "size": size,
                       "browser_download_url": mirror.GITHUB_BASE + tag + "/" + filename})
    return {"tag_name": tag, "draft": False, "prerelease": True,
            "html_url": f"https://github.com/{mirror.REPO}/releases/tag/" + tag,
            "assets": assets}


class MirrorGates(unittest.TestCase):
    def test_selects_real_release_per_platform(self):
        values = [release("windows", "0.20.3"), release("windows", "0.20.4"),
                  release("macos-arm64", "0.20.2")]
        self.assertEqual(mirror.select(values, "windows")["version"], "0.20.4")
        self.assertEqual(mirror.select(values, "macos-arm64")["version"], "0.20.2")

    def test_never_uses_draft_or_unmatched_upstream_asset(self):
        bad = release()
        bad["draft"] = True
        self.assertIsNone(mirror.select([bad], "windows"))
        bad = release()
        bad["assets"][0]["browser_download_url"] = "https://evil.example/payload"
        self.assertIsNone(mirror.select([bad], "windows"))

    def test_accepts_https_release_redirect_hosts_only(self):
        mirror.validate_https(mirror.RELEASES)
        mirror.validate_https(mirror.GITHUB_BASE + "tag/file.exe")
        for url in ("http://github.com/test", "https://evil.example/download",
                    "https://github.com:444/download",
                    "https://user:pass@github.com/download"):
            with self.assertRaises(ValueError):
                mirror.validate_https(url)

    def test_transient_504_retries_then_succeeds(self):
        from unittest.mock import patch
        import urllib.error
        transient = urllib.error.HTTPError(
            mirror.RELEASES, 504, "Gateway Timeout", {}, None)
        with patch.object(mirror.HTTP, "open", side_effect=[transient, transient, "ok"]) as fetch, \\
             patch.object(mirror.time, "sleep") as sleep:
            self.assertEqual(mirror.get(mirror.RELEASES), "ok")
            self.assertEqual(fetch.call_count, 3)
            self.assertEqual(sleep.call_count, 2)

    def test_forbidden_404_does_not_retry(self):
        from unittest.mock import patch
        import urllib.error
        bad = urllib.error.HTTPError(
            mirror.RELEASES, 404, "Not Found", {}, None)
        with patch.object(mirror.HTTP, "open", side_effect=bad) as fetch, \\
             patch.object(mirror.time, "sleep") as sleep:
            with self.assertRaises(urllib.error.HTTPError):
                mirror.get(mirror.RELEASES)
            fetch.assert_called_once()
            sleep.assert_not_called()

    def test_never_silently_decreases_version(self):
        self.assertGreater(mirror.version_key("0.20.4"), mirror.version_key("0.20.3"))


if __name__ == "__main__":
    unittest.main()
