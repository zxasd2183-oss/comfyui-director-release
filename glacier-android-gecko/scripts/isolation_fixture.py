#!/usr/bin/env python3
"""Loopback-only GeckoView cookie + localStorage partition test fixture.

Only artificial test values are stored. No user accounts, proxies, or credentials.
The emulator accesses 127.0.0.1:18765 through adb reverse.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

PORT = 18765
HTML = r"""<!doctype html>
<meta charset="utf-8">
<title>GLACIER_TEST_LOADING</title>
<body>
<h1>Glacier storage isolation test</h1>
<p>Local test values only. No account credentials.</p>
<script>
(() => {
  const phase = new URL(location.href).searchParams.get('phase');
  const cookie = document.cookie.split('; ').find(s => s.startsWith('glacier_ci_space='));
  const val = cookie ? cookie.slice('glacier_ci_space='.length) : null;
  const stored = localStorage.getItem('glacier_ci_space');
  if (phase === 'seed') {
    document.cookie = 'glacier_ci_space=private; Path=/; SameSite=Lax';
    localStorage.setItem('glacier_ci_space', 'private');
    document.title = 'GLACIER_TEST_PRIVATE_SEEDED';
  } else if (phase === 'work') {
    if (val !== null || stored !== null) {
      document.title = 'GLACIER_TEST_WORK_LEAK';
    } else {
      document.cookie = 'glacier_ci_space=work; Path=/; SameSite=Lax';
      localStorage.setItem('glacier_ci_space', 'work');
      document.title = 'GLACIER_TEST_WORK_ISOLATED';
    }
  } else if (phase === 'return') {
    document.title = val === 'private' && stored === 'private'
        ? 'GLACIER_TEST_PRIVATE_RETAINED' : 'GLACIER_TEST_PRIVATE_LOST';
  } else {
    document.title = 'GLACIER_TEST_UNKNOWN_PHASE';
  }
})();
</script>
</body>"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path != '/profile' or parse_qs(parsed.query).get('phase', [''])[0] not in ('seed', 'work', 'return'):
            self.send_error(404)
            return
        encoded = HTML.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt, *args):
        # Log only constant request type, never URL/query or any browser state.
        pass

if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    server.serve_forever()
