"""Contract checks for 111 proxy-prefetch of fixed optional GamePilot assets."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent
INSTALL = (ROOT / "install-gamepilot-component-mirror.sh").read_text()
NGINX = (ROOT / "nginx-gamepilot-components.conf").read_text()
FILENAMES = (
    "gstreamer-1.0-1.26.11-universal.pkg",
    "gstreamer-1.0-1.26.11-universal.pkg.sha256sum",
    "wine-devel-11.18-osx64.tar.xz",
    "gamepilot-wine1118-video-overlay.tar.gz",
)


class GamePilotComponentMirrorTests(unittest.TestCase):
    def test_only_four_fixed_get_routes(self):
        self.assertEqual(NGINX.count("location = "), len(FILENAMES))
        self.assertEqual(NGINX.count("limit_except GET { deny all; }"), len(FILENAMES))
        self.assertNotIn("proxy_pass", NGINX)
        self.assertNotIn("autoindex on", NGINX)
        for name in FILENAMES:
            self.assertIn(
                "location = /downloads/gamepilot-components/" + name, NGINX)
            self.assertIn(
                "/var/lib/glacier-preview-downloads/gamepilot-components/" + name,
                NGINX)

    def test_prefetch_stays_on_111_local_proxy_and_is_fail_closed(self):
        self.assertIn('proxy="http://127.0.0.1:1081"', INSTALL)
        self.assertIn('--proxy "$proxy"', INSTALL)
        self.assertIn("No proxy config/secrets are sent to macOS.", INSTALL)
        self.assertIn('mirror_pinned "$gst_name"', INSTALL)
        self.assertIn('mirror_pinned "wine-devel-11.18-osx64.tar.xz"', INSTALL)
        self.assertIn('mirror_pinned "gamepilot-wine1118-video-overlay.tar.gz"', INSTALL)
        self.assertIn("aa0ea4c82e636ae7bca2076387cb0a5affa26509ad13f119ecd0d62bd7ba6f82", INSTALL)
        self.assertIn("1f9ed57524069df115269c2d95bc4ce3f3cfcde6f3947a770ab61dbfe8eb1699", INSTALL)
        self.assertIn('verify_sha "$probe" "$expected"', INSTALL)
        self.assertIn("nginx -t", INSTALL)
        self.assertIn("systemctl reload nginx", INSTALL)
        self.assertIn("Reverting only GamePilot-components Nginx include", INSTALL)
        self.assertNotRegex(INSTALL, r'(?m)^\s*(wget|pip|apt-get) ')
        self.assertNotIn("location /downloads/gamepilot-components/", NGINX)

if __name__ == "__main__":
    unittest.main()
