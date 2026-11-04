"""No-network, no-root tests for the fail-closed Jipite Nginx route editor."""
import unittest

from configure_jipite_mobile_nginx import (
    MARKER, insert_route, masked_nginx, sections, server_blocks,
)

TWO_VHOSTS = """
server {
    listen 80;
    server_name jipite.borealos.cn;
    return 301 https://$host$request_uri;
}
server {
    listen 8443 ssl;
    server_name jipite.borealos.cn;
    ssl_certificate /etc/nginx/certs/borealos-new/fullchain.cer;
    location / {
        return 200 "Welcome with { braces }";
    }
}
"""


class JipiteNginxTests(unittest.TestCase):
    def test_only_https_vhost_is_modified(self):
        updated = insert_route(TWO_VHOSTS)
        self.assertEqual(updated.count(MARKER), 1)
        self.assertEqual(updated.count("return 301"), 1)
        self.assertEqual(updated.count("ssl_certificate"), 1)
        # New include appears only in the HTTPS block.
        blocks = list(server_blocks(updated))
        self.assertEqual(len(blocks), 2)
        self.assertNotIn(MARKER, updated[blocks[0][0]:blocks[0][1]])
        self.assertIn(MARKER, updated[blocks[1][0]:blocks[1][1]])

    def test_duplicate_route_refused(self):
        once = insert_route(TWO_VHOSTS)
        with self.assertRaises(RuntimeError):
            insert_route(once)

    def test_http_only_refused(self):
        with self.assertRaises(RuntimeError):
            insert_route('server { listen 80; server_name jipite.borealos.cn; }')

    def test_multiple_https_blocks_refused(self):
        only_tls = TWO_VHOSTS[TWO_VHOSTS.index("server {", 3):]
        with self.assertRaises(RuntimeError):
            insert_route(only_tls + only_tls)

    def test_existing_location_refused(self):
        example = TWO_VHOSTS.replace(
            'location / {',
            'location ^~ /api/v1/mobile/ { return 404; }\n    location / {'
        )
        with self.assertRaises(RuntimeError):
            insert_route(example)

    def test_braces_in_quoted_content_dont_break_parser(self):
        example = 'server { listen 443 ssl; server_name jipite.borealos.cn; return 200 "{ }"; }'
        self.assertEqual(len(list(server_blocks(example))), 1)
        self.assertEqual(len(list(server_blocks(insert_route(example)))), 1)

    def test_comments_cannot_forge_server_name(self):
        raw = '''server {
          listen 443 ssl;
          # server_name jipite.borealos.cn;
          server_name another.example;
        }'''
        with self.assertRaises(RuntimeError):
            insert_route(raw)
        self.assertNotIn("server_name jipite.borealos.cn;", masked_nginx(raw))

    def test_nginx_dump_sections(self):
        dump = ('# configuration file /etc/nginx/nginx.conf:\nhttp {}\n' +
                '# configuration file /etc/nginx/conf.d/example.conf:\nserver {}\n')
        self.assertEqual([p for p, _ in sections(dump)],
                         ['/etc/nginx/nginx.conf', '/etc/nginx/conf.d/example.conf'])


if __name__ == "__main__":
    unittest.main()
