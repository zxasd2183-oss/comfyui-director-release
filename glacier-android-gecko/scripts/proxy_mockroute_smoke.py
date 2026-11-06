#!/usr/bin/env python3
"""Self-contained Android 15 Gecko -> SOCKS5 -> synthetic HTTP fixture.

No external socket forwarding, credential, private node, DNS API, or real
server. ADB reverse provides the loopback-only bridge to a local mock SOCKS5
server. This checks Gecko's remote-domain SOCKS5 CONNECT path, not the VLESS
wire protocol or real DNS/HTTPS leakage.
"""
import json
import os
import socket
import socketserver
import struct
import sys
import threading
import time
import traceback
from pathlib import Path

from emulator_smoke_v012 import adb, collect, record, shot, checks, APK, PKG, OUT

SOCKS_PORT = 18566
FAKE_HOST = "glacier-ci.invalid"
PAGE = b"""<!doctype html><html><head><meta charset="utf-8"><title>GLACIER_TEST_PROXY_ROUTE_OK</title></head><body>LOCAL_SOCKS_ROUTE_OK</body></html>"""
observations = []
mu = threading.Lock()

def mark(label):
    with mu:
        observations.append(label)

def receive(sock, n):
    chunks = bytearray()
    while len(chunks) < n:
        block = sock.recv(n-len(chunks))
        if not block:
            raise OSError("Incomplete mock SOCKS5 handshake")
        chunks.extend(block)
    return bytes(chunks)

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        stream = self.request
        stream.settimeout(15)
        try:
            hello = receive(stream,2)
            if hello[0] != 5 or hello[1] > 16:
                return
            methods = receive(stream,hello[1])
            if 0 not in methods:
                stream.sendall(b"\x05\xff")
                return
            stream.sendall(b"\x05\x00")
            request = receive(stream,4)
            if request[:3] != b"\x05\x01\x00":
                return
            if request[3] == 3:
                length = receive(stream,1)[0]
                host = receive(stream,length).decode("ascii","replace").lower()
                mark("remote_dns_domain_atyp")
            elif request[3] == 1:
                receive(stream,4)
                mark("unexpected_ipv4_connect")
                return
            elif request[3] == 4:
                receive(stream,16)
                mark("unexpected_ipv6_connect")
                return
            else:
                return
            port = struct.unpack("!H",receive(stream,2))[0]
            if host != FAKE_HOST or port != 80:
                # Reject everything except one known, artificial host. No
                # generic proxying and no external TCP connections.
                stream.sendall(b"\x05\x02\x00\x01\x00\x00\x00\x00\x00\x00")
                return
            mark("fixture_domain_connect")
            stream.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x50")
            buffer = bytearray()
            while b"\r\n\r\n" not in buffer and len(buffer)<16384:
                chunk=stream.recv(2048)
                if not chunk:
                    break
                buffer.extend(chunk)
            first=bytes(buffer).split(b"\r\n",1)[0]
            if not first.startswith(b"GET / HTTP/1.1"):
                mark("unexpected_http_method")
                return
            if b"host: glacier-ci.invalid" not in bytes(buffer).lower():
                mark("wrong_http_host")
                return
            mark("http_request_arrived_via_socks")
            response=(b"HTTP/1.1 200 OK\r\n"
                      b"Content-Type: text/html; charset=utf-8\r\n"
                      b"Cache-Control: no-store\r\n"
                      b"Connection: close\r\n"
                      + ("Content-Length: %d\r\n\r\n"%len(PAGE)).encode("ascii")+PAGE)
            stream.sendall(response)
            mark("response_delivered_through_socks")
        except (OSError, ValueError):
            # Background Gecko attempts are expected; do not log hosts.
            return

class LocalServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

def smoke():
    if not Path(APK).is_file():
        raise RuntimeError("APK_NOT_FOUND")
    with LocalServer(("127.0.0.1", SOCKS_PORT), Handler) as server:
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            adb("wait-for-device",timeout=90)
            record("android_api",adb("shell","getprop","ro.build.version.sdk").strip())
            adb("install","-r",APK,timeout=180)
            adb("reverse","tcp:18566","tcp:18566",timeout=20)
            record("adb_reverse_fixture","Android SOCKS port mapped to host-only test listener")
            adb("logcat","-c",timeout=20)
            adb("shell","am","start","-W","-n",PKG+"/.MainActivity",
                "--es","glacier.ci.network","mock-socks",timeout=75)
            end=time.monotonic()+110
            rendered=False
            stopped=False
            boot=False
            while time.monotonic()<end:
                log=adb("logcat","-d","-s","GlacierSmoke:I",timeout=20)
                if "PROXY_TEST=MOCK_SOCKS_CONFIGURED" in log:
                    boot=True
                if "PAGE_STOP site=proxy_fixture success=false" in log:
                    raise RuntimeError("MOCK_PROXY_PAGE_LOAD_FAILED")
                if "PAGE_STOP site=proxy_fixture success=true" in log:
                    stopped=True
                if "PROXY_TEST=MOCK_SOCKS_PAGE_RENDERED" in log:
                    rendered=True
                with mu:
                    hits=set(observations)
                required={"remote_dns_domain_atyp","fixture_domain_connect",
                          "http_request_arrived_via_socks","response_delivered_through_socks"}
                if boot and stopped and rendered and required.issubset(hits):
                    break
                time.sleep(2)
            with mu:
                hits=set(observations)
            required={"remote_dns_domain_atyp","fixture_domain_connect",
                      "http_request_arrived_via_socks","response_delivered_through_socks"}
            if "unexpected_ipv4_connect" in hits or "unexpected_ipv6_connect" in hits:
                raise RuntimeError("REMOTE_DNS_NOT_USED_FOR_SOCKS")
            if not boot or not stopped or not rendered or not required.issubset(hits):
                raise RuntimeError("SOCKS_ROUTE_NOT_VERIFIED: boot=%s stop=%s title=%s marks=%s"%(
                    boot,stopped,rendered,",".join(sorted(hits))))
            record("socks_remote_domain","SOCKS5 CONNECT carried fake hostname rather than an IP address")
            record("socks_http_roundtrip","Gecko loaded page body delivered through local mock")
            record("mock_page_rendered","Gecko HTML title and page stop confirmed")
            shot("mock-route-rendered")
            print("PROXY_MOCK_ROUTE_DONE; no external node; real VLESS exit not verified",flush=True)
        finally:
            server.shutdown()

if __name__=="__main__":
    code=0
    try:
        smoke()
    except Exception as ex:
        code=1
        checks.append({"step":"failure","result":"failed","detail":str(ex)})
        traceback.print_exc()
    finally:
        collect()
    sys.exit(code)
