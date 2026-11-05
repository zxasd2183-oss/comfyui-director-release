"""V0.8.1 secure path-based HTTPS route integration (offline only)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import configure_studio_nginx as web
import studio_server

NORMAL = """server {
    listen 8443 ssl;
    server_name jipite.borealos.cn;
    ssl_certificate /etc/nginx/cert.pem;
    location ^~ /api/v1/mobile/ { proxy_pass http://127.0.0.1:8895; }
    location ^~ /app-updates/ { alias /somewhere; }
    location / { return 200 "hello"; }
    include /etc/nginx/snippets/jipite-hub.conf;
}
server { listen 8443 ssl; server_name director.borealos.cn;
    location / { return 200; }
}
"""


class StudioNginxTests(unittest.TestCase):
    def test_route_injected_only_in_correct_tls_vhost(self):
        output, changed = web.patch(NORMAL)
        self.assertTrue(changed)
        self.assertEqual(output.count(web.MARKER), 1)
        self.assertIn("127.0.0.1:8895", output)
        self.assertIn("include /etc/nginx/snippets/jipite-hub.conf;", output)
        self.assertIn("server_name director.borealos.cn;", output)
        unchanged, changed2 = web.patch(output)
        self.assertFalse(changed2)
        self.assertEqual(unchanged, output)

    def test_route_rejects_conflict_or_ambiguity(self):
        conflict = NORMAL.replace("location / { return 200",
            "location ^~ /studio/ { proxy_pass http://127.0.0.1:9999; }\n    location / { return 200")
        with self.assertRaisesRegex(RuntimeError, "Existing /studio"):
            web.patch(conflict)
        with self.assertRaisesRegex(RuntimeError, "Ambiguous"):
            web.patch("server { server_name other.example; listen 443 ssl; }")
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            web.patch(NORMAL + "\n" + web.MARKER + "\n" + web.MARKER)

    def test_public_snippet_has_password_gate_and_strips_authorization(self):
        config = (Path(__file__).resolve().parents[1] /
                  "nginx-jipite-studio.conf").read_text()
        self.assertIn('auth_basic "Director Studio private operator console"', config)
        self.assertIn("auth_basic_user_file /etc/nginx/.director-studio-htpasswd;", config)
        self.assertIn("proxy_pass http://127.0.0.1:8900/;", config)
        self.assertIn('proxy_set_header Authorization "";', config)
        self.assertIn('proxy_set_header Cookie "";', config)
        self.assertIn("proxy_buffering off;", config)
        self.assertNotIn("0.0.0.0:8900", config)

    def test_strict_worker_gid(self):
        class User:
            pw_gid = 1234
        with patch.object(web.pwd, "getpwnam", return_value=User()) as mock:
            self.assertEqual(web.worker_gid("user www-data;\nserver {}"), 1234)
            mock.assert_called_once_with("www-data")
        with self.assertRaisesRegex(RuntimeError, "worker user"):
            web.worker_gid("server {}")

    def test_frontend_uses_relative_assets_and_api(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "index.html").read_text()
        js = (root / "studio.js").read_text()
        self.assertIn('href="./studio.css"', html)
        self.assertIn('src="./studio.js"', html)
        self.assertIn('fetch("./api/v1/snapshot"', js)
        self.assertIn('EventSource("./api/v1/stream"', js)
        self.assertNotIn('fetch("/api/v1/', js)

    def test_host_and_csrf_policy_stays_strict(self):
        self.assertEqual(studio_server.HOSTS, {
            "127.0.0.1:8900", "localhost:8900"})
        self.assertEqual(studio_server.CSP.count("frame-ancestors 'none'"), 1)


if __name__ == "__main__":
    unittest.main()
