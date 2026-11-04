import http.server
import json
import secrets
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bridge import build_handler

class Upstream(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_POST(self):
        assert self.path == "/mcp"
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        output = {"jsonrpc":"2.0","id":request["id"],
                  "result":{"tools":[{"name":"get_gpu_power_status"}]}}
        data = json.dumps(output).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.secret = secrets.token_hex(32)
        cls.upstream = http.server.ThreadingHTTPServer(("127.0.0.1",0),Upstream)
        cls.up_thread = threading.Thread(target=cls.upstream.serve_forever,daemon=True)
        cls.up_thread.start()
        target=f"http://127.0.0.1:{cls.upstream.server_port}/mcp"
        cls.bridge = http.server.ThreadingHTTPServer(("127.0.0.1",0),build_handler(cls.secret,target))
        cls.b_thread = threading.Thread(target=cls.bridge.serve_forever,daemon=True)
        cls.b_thread.start()
        cls.base=f"http://127.0.0.1:{cls.bridge.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.bridge.shutdown()
        cls.bridge.server_close()
        cls.upstream.shutdown()
        cls.upstream.server_close()

    def test_valid_token_forwards_mcp(self):
        body=b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
        url=self.base+"/mcp/"+self.secret
        req=Request(url,data=body,headers={"Content-Type":"application/json","Accept":"application/json"})
        with urlopen(req,timeout=5) as resp:
            self.assertEqual(resp.status,200)
            result=json.loads(resp.read())
        self.assertEqual(result["result"]["tools"][0]["name"],"get_gpu_power_status")

    def test_invalid_url_rejected(self):
        body=b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
        req=Request(self.base+"/mcp/notasecret",data=body,
                    headers={"Content-Type":"application/json"})
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req,timeout=5)
        self.assertEqual(ctx.exception.code,404)

    def test_origin_rejected(self):
        req=Request(self.base+"/mcp/"+self.secret,data=b"{}",
                    headers={"Content-Type":"application/json","Origin":"https://attacker.example"})
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req,timeout=5)
        self.assertEqual(ctx.exception.code,404)

    def test_size_limit(self):
        req=Request(self.base+"/mcp/"+self.secret,data=b"x"*(256*1024+1),
                    headers={"Content-Type":"application/json"})
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req,timeout=5)
        self.assertEqual(ctx.exception.code,413)

if __name__=="__main__":
    unittest.main()
