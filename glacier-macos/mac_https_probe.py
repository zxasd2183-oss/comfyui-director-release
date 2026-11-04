"""Mac-only verified TLS probe over existing SOCKS5 proxy.

Python's OpenSSL defaults inside a frozen .app may not contain the system CA
chain. Bundle a current Mozilla CA root set and keep full hostname+chain checks.
Never disable verification or fall back to direct network access.
"""
from __future__ import annotations
import socket
import ssl
import struct
from pathlib import Path

import certifi
from ui08 import read_exact


def create_tls_context():
    bundle=Path(certifi.where())
    if not bundle.is_file() or bundle.stat().st_size < 100_000:
        raise RuntimeError("Mac 安装包缺少可信 CA 根证书，已禁止未验证的 HTTPS 连接")
    context=ssl.create_default_context(cafile=str(bundle))
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise RuntimeError("Mac HTTPS 证书验证未启用，已阻止测试")
    return context


def check_via_socks(port,host="www.google.com",path="/generate_204"):
    if not 1<=int(port)<=65535:
        raise ValueError("无效本地 SOCKS5 端口")
    domain=host.encode("idna")
    if not 1<=len(domain)<=255:
        raise ValueError("无效 HTTPS 目标域名")
    # Explicitly contact the local proxy only. No direct-network fallback.
    with socket.create_connection(("127.0.0.1",port),timeout=7) as sock:
        sock.settimeout(9)
        sock.sendall(b"\x05\x01\x00")
        if read_exact(sock,2)!=b"\x05\x00":
            raise OSError("本地 SOCKS5 握手失败")
        sock.sendall(b"\x05\x01\x00\x03"+bytes([len(domain)])+domain+struct.pack("!H",443))
        reply=read_exact(sock,4)
        if reply[:3]!=b"\x05\x00\x00":
            raise OSError("VLESS 线路未能连接到测试目标")
        atyp=reply[3]
        if atyp==1:
            read_exact(sock,4)
        elif atyp==4:
            read_exact(sock,16)
        elif atyp==3:
            read_exact(sock,read_exact(sock,1)[0])
        else:
            raise OSError("SOCKS5 返回了无效的地址格式")
        read_exact(sock,2)
        try:
            with create_tls_context().wrap_socket(sock,server_hostname=host) as secure:
                secure.settimeout(9)
                secure.sendall((
                    "GET "+path+" HTTP/1.1\r\n"
                    "Host: "+host+"\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii"))
                first=b""
                while b"\r\n" not in first and len(first)<256:
                    part=secure.recv(64)
                    if not part:break
                    first+=part
                line=first.split(b"\r\n",1)[0]
                if line.startswith(b"HTTP/") and b" 204 " in line:
                    return True,"Google HTTPS 检测成功（CA 证书链及域名均通过）"
                raise OSError("Google 未返回预期的 204 响应")
        except ssl.SSLCertVerificationError as exc:
            raise OSError(
                "HTTPS 证书验证未通过；证书链不受信任或线路存在 TLS 拦截。"
                "未关闭证书验证。详细原因："+str(exc)[:120]
            ) from exc
