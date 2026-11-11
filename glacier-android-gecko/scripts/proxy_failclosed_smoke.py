#!/usr/bin/env python3
"""Offline-SOCKS Gecko failure regression. No real node, credentials, or secrets.

Separate Android 15 emulator job to avoid reusing the DIRECT GeckoRuntime.
This proves one external HTTPS request fails via the *proxy* error path, not
that live VLESS/DNS/IP-leak protection has passed a security audit.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

from emulator_smoke_v012 import adb, shot, collect, record, APK, PKG, checks, OUT

def run():
    if not Path(APK).is_file():
        raise RuntimeError("APK_NOT_FOUND")
    adb("wait-for-device", timeout=90)
    record("android_api", adb("shell","getprop","ro.build.version.sdk").strip())
    adb("install", "-r", APK, timeout=180)
    adb("logcat", "-c", timeout=20)
    adb("shell", "am", "start", "-W", "-n", PKG+"/.MainActivity",
        "--es", "glacier.ci.network", "offline-socks", timeout=75)
    deadline=time.monotonic()+90
    found_boot=False
    refusal=False
    while time.monotonic()<deadline:
        log=adb("logcat","-d","-s","GlacierSmoke:I",timeout=20)
        if "PROXY_TEST=OFFLINE_SOCKS_CONFIGURED" in log:
            found_boot=True
        if "PAGE_STOP site=example success=true" in log:
            raise RuntimeError("CRITICAL_DIRECT_FALLBACK: external website loaded without SOCKS")
        if "PROXY_OFFLINE_ERROR=other" in log:
            raise RuntimeError("NOT_A_PROXY_REFUSAL: inspect Gecko network error category")
        if "PROXY_OFFLINE_ERROR=proxy_refused" in log:
            refusal=True
            break
        time.sleep(3)
    if not found_boot:
        raise RuntimeError("OFFLINE_PROXY_DEBUG_RUNTIME_NOT_STARTED")
    if not refusal:
        raise RuntimeError("EXPECTED_PROXY_CONNECTION_REFUSED_NOT_OBSERVED")
    record("proxy_refusal", "Gecko reported proxy-category connection refused for example.com")

    # Read the actual on-device Gecko prefs. Failure to set any fail-closed
    # option must fail CI even if the error callback happened.
    prefs=adb("shell", "run-as", PKG, "cat", "no_backup/gecko-network.yaml",
              timeout=20)
    expected=[
        "network.proxy.type: 1",
        "network.proxy.socks: \"127.0.0.1\"",
        "network.proxy.socks_remote_dns: true",
        "network.proxy.failover_direct: false",
        "network.proxy.allow_hijacking_localhost: true",
        "network.trr.mode: 5",
        "media.peerconnection.enabled: false",
    ]
    for pref in expected:
        if pref not in prefs:
            raise RuntimeError("MISSING_FAIL_CLOSED_PREF: "+pref.split(":")[0])
    record("manual_proxy_preferences","SOCKS5 / remote-DNS / no direct fallback / WebRTC off")

    # Catch a late successful load after the initial error.
    time.sleep(6)
    log=adb("logcat","-d","-s","GlacierSmoke:I",timeout=20)
    if "PAGE_STOP site=example success=true" in log:
        raise RuntimeError("CRITICAL_LATE_DIRECT_FALLBACK")
    record("offline_proxy_fail_closed", "external HTTPS stayed blocked with SOCKS down")
    shot("proxy-offline")
    print("PROXY_FAIL_CLOSED_SMOKE_DONE: negative SOCKS test only; real VLESS exit NOT VERIFIED",flush=True)

if __name__=="__main__":
    code=0
    try:
        run()
    except Exception as exc:
        code=1
        checks.append({"step":"failure","result":"failed","detail":str(exc)})
        traceback.print_exc()
    finally:
        collect()
    sys.exit(code)
