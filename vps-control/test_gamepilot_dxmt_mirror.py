#!/usr/bin/env python3
"""Static integrity/route checks for the three immutable GamePilot FOSS assets.

The owner VPS performs the real proxy download and FULL external HTTPS
SHA256 check; CI never contacts or modifies the production VPS.
"""
from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = (HERE / "install-gamepilot-dxmt-mirror.sh").read_text("utf-8")
NGINX = (HERE / "nginx-gamepilot-dxmt-downloads.conf").read_text("utf-8")

FILES = {
    "winecx-24.0.7_7.tar.xz": (
        "172348356", "203f9e9fd6c2cc77e6525d798a434ced326145db34a356355e05659d3445fd1c",
        "https://github.com/Sikarugir-App/Engines/releases/download/v1.0/WS12WineCX24.0.7_7.tar.xz"
    ),
    "dxmt-0.74-builtin.tar.gz": (
        "18990005", "2598981a8b725653773e277470a95dda4253b8a14d36e0dc96dce0e3800f0ceb",
        "https://github.com/3Shain/dxmt/releases/download/v0.74/dxmt-v0.74-builtin.tar.gz"
    ),
    "wine-stable-11.0_1-libs.tar.xz": (
        "185303032", "b50dc50ec7f41d58b115a6b685d4d1315ba3c797bd3aa0f49213f2703cb82388",
        "https://github.com/Gcenx/macOS_Wine_builds/releases/download/11.0_1/wine-stable-11.0_1-osx64.tar.xz"
    ),
}


class TestFreeDXMTMirror(unittest.TestCase):
    def test_exactly_three_immutable_routes_no_uploads(self):
        locations = re.findall(r"^location\s+=\s+([^\s{]+)\s*\{", NGINX, re.M)
        self.assertEqual(set(locations), {
            f"/downloads/gamepilot-dxmt/{name}" for name in FILES
        })
        self.assertEqual(len(locations), 3)
        self.assertNotIn("proxy_pass", NGINX)
        self.assertNotIn("autoindex on", NGINX)
        self.assertNotRegex(NGINX, r"(?m)^location\s+~")
        self.assertEqual(NGINX.count("limit_except GET { deny all; }"), 3)
        self.assertEqual(NGINX.count("disable_symlinks on;"), 3)
        for name in FILES:
            self.assertIn(
                f"alias /var/lib/glacier-preview-downloads/gamepilot-dxmt/{name};",
                NGINX
            )

    def test_all_pins_and_upstreams_match_reviewed_release_metadata(self):
        for name, (length, digest, url) in FILES.items():
            self.assertIn(f"{name}|{url}|{length}|{digest}", SCRIPT)
            self.assertIn(f"{name}|{length}|{digest}", SCRIPT)
            self.assertEqual(len(digest), 64)
        self.assertIn("http://127.0.0.1:1081", SCRIPT)
        self.assertIn("sha256sum", SCRIPT)
        self.assertIn('valid "$probe" "$bytes" "$digest"', SCRIPT)
        self.assertIn("systemctl reload nginx", SCRIPT)
        self.assertIn("Rolling back ONLY the GamePilot DXMT Nginx route", SCRIPT)

    def test_existing_release_and_glacier_configs_untouched(self):
        self.assertIn(
            'host="/etc/nginx/snippets/glacier-preview-downloads.conf"', SCRIPT)
        self.assertIn(
            'route="/etc/nginx/snippets/gamepilot-dxmt-downloads.conf"', SCRIPT)
        self.assertNotIn("sites-enabled", SCRIPT)
        self.assertNotIn("sed -i", SCRIPT)
        self.assertNotIn("chmod 777", SCRIPT)
        self.assertNotIn("eval ", SCRIPT)


if __name__ == "__main__":
    unittest.main()
