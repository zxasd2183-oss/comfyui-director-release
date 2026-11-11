"""Real REALITY end-to-end test with official Xray 26.11.9 on local loopback.

Xray server REALITY + Xray browser SOCKS client. No private user's link,
VPS, Internet access, external site, or persistent credentials used.
"""
from __future__ import annotations

import base64
import json
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from main import parse_node
from mac_xray_reality import build_xray_reality_config


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]


def _receive(sock,length):
    data=b""
    while len(data)<length:
        part=sock.recv(length-len(data))
        if not part:
            raise ConnectionError("SOCKS tunnel terminated")
        data+=part
    return data


def _await_port(port,process):
    for _ in range(120):
        if process.poll() is not None:
            raise AssertionError("Xray exited before binding local test listener")
        try:
            with socket.create_connection(("127.0.0.1",port),timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("Xray failed to bind local test listener")


class XrayRealityLoopbackTests(unittest.TestCase):
    def test_real_reality_handshake_and_socks5_data_relay(self):
        core=Path("bin/xray")
        self.assertTrue(core.is_file(),"Official Apple Silicon Xray binary missing")
        secret=X25519PrivateKey.generate()
        pub=base64.urlsafe_b64encode(secret.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )).decode().rstrip("=")
        priv=base64.urlsafe_b64encode(secret.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )).decode().rstrip("=")
        user=str(uuid.uuid4())
        relay_port=_free_port()
        server_port=_free_port()
        socks_port=_free_port()

        # A local TCP service acts as the final destination of an authenticated
        # VLESS relay. It never performs direct public-network I/O.
        received=[]
        def relay():
            with socket.socket() as listener:
                listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                listener.bind(("127.0.0.1",relay_port))
                listener.listen(2)
                listener.settimeout(12)
                try:
                    conn,_=listener.accept()
                    with conn:
                        conn.settimeout(8)
                        received.append(_receive(conn,4))
                        conn.sendall(b"pong")
                except (OSError,ConnectionError):
                    pass
        relay_thread=threading.Thread(target=relay,daemon=True)
        relay_thread.start()

        server={
            "log":{"loglevel":"debug","access":"none"},
            "inbounds":[{
                "listen":"127.0.0.1","port":server_port,
                "protocol":"vless",
                "settings":{"clients":[{"id":user}],"decryption":"none"},
                "streamSettings":{
                    "network":"tcp","security":"reality",
                    "realitySettings":{
                        "target":"www.example.com:443",
                        "serverNames":["www.example.com"],
                        "privateKey":priv,"shortIds":["1a2b"],
                    }
                }
            }],
            # Modern Xray blocks private destinations by default for safety.
            # Permit ONLY this test's ephemeral loopback TCP port; never ship
            # this override in the real Glacier client or server.
            "outbounds":[{"protocol":"freedom","tag":"direct",
                          "settings":{"finalRules":[{
                              "action":"allow","network":"tcp",
                              "ip":["127.0.0.1/32"],"port":str(relay_port)
                          }]}}]
        }
        link=(f"vless://{user}@127.0.0.1:{server_port}?"
              f"encryption=none&security=reality&type=tcp"
              f"&sni=www.example.com&pbk={pub}&sid=1a2b&fp=chrome")
        client=build_xray_reality_config(parse_node(link),socks_port)
        client["log"]["loglevel"]="debug"
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            server_cfg=folder/"server.json"
            client_cfg=folder/"client.json"
            server_cfg.write_text(json.dumps(server))
            client_cfg.write_text(json.dumps(client))
            for cfg in [server_cfg,client_cfg]:
                check=subprocess.run([str(core),"run","-test","-config",str(cfg)],
                                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
                self.assertEqual(check.returncode,0,"local REALITY fixture config failed")
            procs=[]
            traces=[]
            def read_synthetic_trace(proc,role):
                # Only synthetic loopback fixtures are present in this test.
                # Do not emit raw node data from user-configured environments.
                import re
                for raw in iter(proc.stdout.readline,b""):
                    line=raw.decode("utf-8",errors="replace")
                    line=re.sub(r"[A-Za-z0-9_-]{32,}","[redacted]",line)
                    traces.append(role+": "+line.strip()[:300])
            try:
                for role,cfg,port in [("server",server_cfg,server_port),("client",client_cfg,socks_port)]:
                    proc=subprocess.Popen([str(core),"run","-config",str(cfg)],
                                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                    procs.append(proc)
                    threading.Thread(target=read_synthetic_trace,args=(proc,role),
                                     daemon=True).start()
                    _await_port(port,proc)
                with socket.create_connection(("127.0.0.1",socks_port),timeout=7) as sock:
                    sock.settimeout(8)
                    sock.sendall(b"\x05\x01\x00")
                    self.assertEqual(_receive(sock,2),b"\x05\x00")
                    sock.sendall(b"\x05\x01\x00\x01"+socket.inet_aton("127.0.0.1")+
                                 relay_port.to_bytes(2,"big"))
                    reply=_receive(sock,4)
                    self.assertEqual(reply[:2],b"\x05\x00",
                                     "Xray REALITY SOCKS5 connect rejected")
                    if reply[3]==1:
                        _receive(sock,4)
                    elif reply[3]==3:
                        _receive(sock,_receive(sock,1)[0])
                    elif reply[3]==4:
                        _receive(sock,16)
                    _receive(sock,2)
                    sock.sendall(b"ping")
                    try:
                        echoed=_receive(sock,4)
                    except (TimeoutError,OSError,ConnectionError) as exc:
                        time.sleep(0.2)
                        self.fail("Xray REALITY loopback relay failed: "+type(exc).__name__
                                  +" -- "+" | ".join(traces[-18:]))
                    self.assertEqual(echoed,b"pong")
                relay_thread.join(timeout=3)
                self.assertEqual(received,[b"ping"])
            finally:
                for proc in procs:
                    proc.terminate()
                for proc in procs:
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill();proc.wait(timeout=5)


if __name__=="__main__":
    unittest.main()
