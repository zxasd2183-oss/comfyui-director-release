"""Real sing-box integration test: prove SOCKS failure appears in captured stdout.

All traffic stays on loopback. The fake VLESS endpoint intentionally refuses
connections; no real user node, UUID, certificate or public network is needed.
"""
from __future__ import annotations

import json
import socket
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from main import build_proxy_config
from mac_proxy_diagnostics import start_capture, latest_hint


def recv_exact(sock,n):
    data=b""
    while len(data)<n:
        chunk=sock.recv(n-len(data))
        if not chunk:
            raise OSError("unexpected EOF from local SOCKS5")
        data+=chunk
    return data


class RealSingBoxLogCaptureTests(unittest.TestCase):
    def test_failed_vless_outbound_produces_redacted_stdout_diagnostic(self):
        core=Path("bin/sing-box")
        self.assertTrue(core.is_file(),"Official bundled sing-box binary missing")
        # Keep the destination socket bound but NOT listening: ECONNREFUSED.
        with socket.socket() as unserved, socket.socket() as listener:
            unserved.bind(("127.0.0.1",0))
            destination_port=unserved.getsockname()[1]
            listener.bind(("127.0.0.1",0))
            listen_port=listener.getsockname()[1]
            link=("vless://"+str(uuid.UUID(int=1))+
                  f"@127.0.0.1:{destination_port}?encryption=none&security=none")
            config=build_proxy_config(link,listen_port)
            with tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/"config.json"
                path.write_text(json.dumps(config),encoding="utf-8")
                check=subprocess.run([str(core),"check","-c",str(path)],
                                     stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)
                self.assertEqual(check.returncode,0,"synthetic local-only config must validate")
                proc=subprocess.Popen([str(core),"run","-c",str(path)],
                                      stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                try:
                    start_capture(proc)
                    for _ in range(100):
                        self.assertIsNone(proc.poll(),"sing-box exited before local bind")
                        try:
                            client=socket.create_connection(("127.0.0.1",listen_port),timeout=0.2)
                            break
                        except OSError:
                            time.sleep(0.04)
                    else:
                        self.fail("sing-box did not start local SOCKS5")
                    with client:
                        client.settimeout(6)
                        client.sendall(b"\x05\x01\x00")
                        self.assertEqual(recv_exact(client,2),b"\x05\x00")
                        host=b"www.google.com"
                        client.sendall(b"\x05\x01\x00\x03"+bytes([len(host)])+host+b"\x01\xbb")
                        reply=recv_exact(client,4)
                        self.assertEqual(reply[0],5)
                        self.assertNotEqual(reply[1],0,"synthetic endpoint was not listening")
                    hint=None
                    for _ in range(60):
                        hint=latest_hint(proc)
                        if hint:
                            break
                        time.sleep(0.05)
                    self.assertEqual(hint,"节点服务拒绝连接",
                        "sing-box runtime stdout error did not reach redacted UI hint classifier")
                finally:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)


if __name__=="__main__":
    unittest.main()
