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

TRANSFER_HTML = r"""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GLACIER_TEST_TRANSFER_READY</title>
<style>
body {font:24px sans-serif;margin:20px;background:#fff}
button {display:block;font-size:24px;margin:20px 0;padding:24px;min-height:70px}
</style>
<h1>Glacier transfer fixture</h1>
<input id="upload" type="file" accept="text/plain" style="display:none">
<button id="upload-btn" onclick="document.querySelector('#upload').click()">选择测试文件</button>
<button id="download-btn" onclick="location.href='/test-attachment'">保存测试下载</button>
<script>
document.querySelector('#upload').addEventListener('change',async (event)=>{
 const file=event.target.files[0];
 if(!file){document.title='GLACIER_TEST_UPLOAD_CANCELLED';return;}
 const text=await file.text();
 if(file.name!=='glacier-upload-test.txt' || text!=='GLACIER_UPLOAD_TEST\n') {
   document.title='GLACIER_TEST_UPLOAD_WRONG_FILE';
   return;
 }
 try {
   const response=await fetch('/upload', {
      method:'POST', body:file, cache:'no-store',
      headers:{'Content-Type':'text/plain'}
   });
   const result=await response.text();
   document.title=(response.ok && result==='GLACIER_UPLOAD_BYTES_VERIFIED')
       ? 'GLACIER_TEST_UPLOAD_OK':'GLACIER_TEST_UPLOAD_REJECTED';
 } catch(err) {
   document.title='GLACIER_TEST_UPLOAD_NETWORK_ERROR';
 }
});
</script>
"""
DOWNLOAD_BODY = b"GLACIER_DOWNLOAD_TEST\n"

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Only a known, fake test payload may be received. No user documents.
        if urlsplit(self.path).path != '/upload':
            self.send_error(404)
            return
        try:
            n = int(self.headers.get('Content-Length','-1'))
        except ValueError:
            n = -1
        if n < 0 or n > 1024 * 1024:
            self.send_error(413)
            return
        actual = self.rfile.read(n)
        if actual != b'GLACIER_UPLOAD_TEST\n':
            self.send_error(422)
            return
        result = b'GLACIER_UPLOAD_BYTES_VERIFIED'
        self.send_response(200)
        self.send_header('Content-Type','text/plain')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(result)))
        self.end_headers()
        self.wfile.write(result)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == '/test-attachment':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="glacier-download-test.txt"')
            self.send_header('Content-Length', str(len(DOWNLOAD_BODY)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(DOWNLOAD_BODY)
            return
        if parsed.path == '/transfer':
            page = TRANSFER_HTML
        elif parsed.path == '/profile' and parse_qs(parsed.query).get('phase', [''])[0] in ('seed', 'work', 'return'):
            page = HTML
        else:
            self.send_error(404)
            return
        encoded = page.encode('utf-8')
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
