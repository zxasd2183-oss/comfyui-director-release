"""Translate parsed VLESS REALITY options to official Xray-core configuration.

Why Xray? Newer Xray REALITY servers may reject sing-box 1.14 ClientHello
(which lacks the required X25519MLKEM768-first key share). The official
Xray client provides compatible REALITY handshakes without weakening TLS.
Inputs are the existing validated parse_node() output; no user secrets logged.
"""
from __future__ import annotations

import re


def build_xray_reality_config(node: dict, port: int) -> dict:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("无效本地代理端口")
    if node.get("type") != "vless":
        raise ValueError("仅支持 VLESS 节点")
    tls = node.get("tls") or {}
    reality = tls.get("reality") or {}
    if not reality.get("enabled") or not reality.get("public_key"):
        raise ValueError("此 Xray 配置只用于 REALITY")
    sid = reality.get("short_id", "")
    if not isinstance(sid, str) or not re.fullmatch(r"(?:[a-fA-F0-9]{2}){0,8}", sid):
        raise ValueError("REALITY shortId 必须是偶数长度的十六进制字符串，最多16位")
    fp = (tls.get("utls") or {}).get("fingerprint") or "chrome"
    if not isinstance(fp, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", fp):
        raise ValueError("REALITY 指纹格式无效")
    user = {"id": node["uuid"], "encryption": "none"}
    if node.get("flow"):
        user["flow"] = node["flow"]
    transport = node.get("transport") or {"type": "tcp"}
    kind = transport.get("type", "tcp")
    stream = {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
            "serverName": tls.get("server_name") or node["server"],
            "fingerprint": fp,
            "publicKey": reality["public_key"],
            "shortId": sid.lower(),
        },
    }
    if kind == "tcp":
        pass
    elif kind == "ws":
        stream["network"] = "ws"
        settings = {"path": transport.get("path", "/")}
        headers = transport.get("headers") or {}
        if headers:
            settings["headers"] = dict(headers)
        # Xray wsSettings supports early-data from sharing links via
        # path's ?ed= syntax; it is not equivalent to sing-box's header config.
        # Reject it rather than silently changing authentication transport.
        if transport.get("max_early_data"):
            raise ValueError("REALITY+WebSocket Early Data 暂不支持 Xray 自动转换")
        stream["wsSettings"] = settings
    elif kind == "grpc":
        stream["network"] = "grpc"
        stream["grpcSettings"] = {"serviceName": transport.get("service_name","")}
    elif kind == "httpupgrade":
        stream["network"] = "httpupgrade"
        stream["httpupgradeSettings"] = {
            "path": transport.get("path","/"),
            "host": transport.get("host",""),
        }
    else:
        raise ValueError("REALITY 传输类型不支持："+str(kind)[:30])
    return {
        "log": {"loglevel": "warning", "access": "none"},
        "inbounds": [{
            "tag": "local-socks", "listen": "127.0.0.1", "port": port,
            "protocol": "socks", "settings": {"auth": "noauth", "udp": False},
        }],
        "outbounds": [{
            "tag": "node", "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": node["server"], "port": node["server_port"],
                    "users": [user],
                }],
            },
            "streamSettings": stream,
        }],
        "routing": {"domainStrategy": "AsIs", "rules": []},
    }
