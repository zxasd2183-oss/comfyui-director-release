#!/usr/bin/env python3
"""Read-only, redacted provider connectivity diagnostic for owner-direct GPU power.

Never starts/stops instances, opens public services, changes credentials, or
prints instance IDs, API keys, raw provider responses, or exception text.
Run only on the trusted VPS through the existing root Python environment.
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import sys
from pathlib import Path

from power_ops import read_env_file, create_provider_client

PROVIDER_HOST = "api.compshare.cn"
SOURCE_ENV = "/etc/comfyui-director-control.env"


def dns_check():
    answers = socket.getaddrinfo(PROVIDER_HOST, 443, type=socket.SOCK_STREAM)
    if not answers:
        raise OSError("no addresses")


def tls_check():
    context = ssl.create_default_context()
    with socket.create_connection((PROVIDER_HOST, 443), timeout=6) as sock:
        with context.wrap_socket(sock, server_hostname=PROVIDER_HOST) as tls:
            if tls.version() not in ("TLSv1.2", "TLSv1.3"):
                raise ssl.SSLError("TLS below minimum")


def instance_check(config):
    """Perform ONLY the official DescribeCompShareInstance read-only API call."""
    client = create_provider_client(config)
    response = client.ucompshare().invoke("DescribeCompShareInstance", {
        "Region": config["COMP_REGION"],
        "Zone": config["COMP_ZONE"],
        "UHostIds": [config["COMP_UHOST_ID"]],
    })
    if not isinstance(response, dict) or response.get("RetCode") != 0:
        return {"ok": False, "stage": "provider", "reason": "provider_rejected"}
    entries = response.get("UHostSet")
    if not isinstance(entries, list):
        return {"ok": False, "stage": "provider", "reason": "provider_response_invalid"}
    hits = [item for item in entries if isinstance(item, dict)
            and item.get("UHostId") == config["COMP_UHOST_ID"]]
    if len(hits) != 1:
        return {"ok": False, "stage": "instance", "reason": "configured_instance_not_found"}
    record = hits[0]
    if (record.get("Region", config["COMP_REGION"]) != config["COMP_REGION"] or
            record.get("Zone", config["COMP_ZONE"]) != config["COMP_ZONE"]):
        return {"ok": False, "stage": "instance", "reason": "configured_region_zone_mismatch"}
    state = record.get("State")
    if state not in ("Stopped", "Running", "Starting", "Stopping",
                     "Install", "Rebooting"):
        return {"ok": False, "stage": "instance", "reason": "instance_state_not_supported"}
    return {"ok": True, "stage": "ready", "mode": "owner_direct",
            "approval_required": False, "provider_state": state,
            "instance_matched": True,
            "power_operation_executed": False,
            "stop_requires_verified_empty_queue": True}


def diagnose(*, config_fn=None, dns_fn=dns_check, tls_fn=tls_check,
             instance_fn=instance_check, uid_fn=os.geteuid):
    if uid_fn() != 0:
        return {"ok": False, "stage": "local", "reason": "root_required"}
    try:
        cfg = config_fn() if config_fn is not None else read_env_file(SOURCE_ENV)
    except Exception:
        return {"ok": False, "stage": "configuration",
                "reason": "credential_or_instance_configuration_invalid"}
    required=("COMP_PUBLIC_KEY","COMP_PRIVATE_KEY","COMP_UHOST_ID",
              "COMP_REGION","COMP_ZONE")
    if not isinstance(cfg,dict) or not all(isinstance(cfg.get(k),str) and cfg[k]
                                          for k in required):
        return {"ok": False, "stage": "configuration", "reason": "required_fields_missing"}
    try:
        dns_fn()
    except Exception:
        return {"ok": False, "stage": "dns", "reason": "provider_hostname_unreachable"}
    try:
        tls_fn()
    except Exception:
        return {"ok": False, "stage": "tls",
                "reason": "provider_https_connection_failed"}
    try:
        result = instance_fn(cfg)
    except Exception:
        # SDK/auth errors often contain private request metadata; redact them.
        return {"ok": False, "stage": "provider",
                "reason": "provider_sdk_auth_or_request_failed"}
    if (not isinstance(result,dict) or
            result.get("ok") not in (True,False) or
            result.get("stage") not in ("provider","instance","ready")):
        return {"ok": False, "stage": "provider",
                "reason": "provider_result_invalid"}
    allowed={"ok","stage","reason","mode","approval_required","provider_state",
             "instance_matched","power_operation_executed",
             "stop_requires_verified_empty_queue"}
    return {key:value for key,value in result.items() if key in allowed}


def main():
    result=diagnose()
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    raise SystemExit(0 if result["ok"] else 2)


if __name__=="__main__":
    main()
