#!/usr/bin/env python3
"""Probes GeckoView proxy fail-closed behavior with an UNREACHABLE test VLESS node.

203.0.113.1 is the RFC 5737 TEST-NET-3 documentation address, not a real node.
This never exercises a working VLESS tunnel and must not be reported as such.
"""
import importlib.util
import pathlib
import time
import traceback
import sys
import re

src=pathlib.Path("scripts/glacier_android_ci_smoke.py")
spec=importlib.util.spec_from_file_location("glacier_ui",src)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
out=pathlib.Path("glacier-android-gecko/build/reports/proxy-fail-closed")
out.mkdir(parents=True,exist_ok=True)

def content():
    return "\n".join(n.attrib.get("text","") for n in m.ui()
                if n.attrib.get("class")!="android.widget.EditText")

def save(label):
    try:
        m.adb("shell","uiautomator","dump","/sdcard/glacier-proxy.xml",timeout=22,checked=False)
        m.adb("pull","/sdcard/glacier-proxy.xml",str(out/(label+".xml")),timeout=16,checked=False)
    except Exception as e:print("UI dump unavailable:",str(e),flush=True)
    try:
        m.adb("shell","screencap","-p","/sdcard/glacier-proxy.png",timeout=16)
        m.adb("pull","/sdcard/glacier-proxy.png",str(out/(label+".png")),timeout=16)
    except Exception as e:print("Screenshot unavailable:",str(e),flush=True)

def run():
    print("=== VLESS UNREACHABLE NODE FAIL-CLOSED EXPERIMENT ===",flush=True)
    m.adb("install","-r",m.APK,timeout=160)
    m.adb("shell","pm","clear",m.PKG)
    m.adb("shell","am","start","-W","-n",m.PKG+"/.MainActivity",timeout=35)
    m.tap("导入 VLESS 节点")
    print("Supplying RFC5737 unreachable dummy node (no secret)",flush=True)
    node="vless://123e4567-e89b-12d3-a456-426614174000@203.0.113.1:443?security=tls"
    edit=None
    for x in m.ui():
        if x.attrib.get("class")=="android.widget.EditText":
            b=re.findall(r"\d+",x.attrib.get("bounds",""))
            if len(b)==4:
                nums=list(map(int,b))
                edit=((nums[0]+nums[2])//2,(nums[1]+nums[3])//2)
                break
    if edit is None:raise AssertionError("VLESS link input field not found")
    m.adb("shell","input","tap",str(edit[0]),str(edit[1]))
    m.adb("shell","input","text",node,timeout=35)
    m.tap("启动代理")
    m.wait_for("VLESS 本地代理运行中",seconds=60)
    print("PASS: bundled sing-box executable started and loopback SOCKS was detected",flush=True)
    m.alive()
    save("socks-local-listener")

    # Gecko has automatically attempted the initial https://example.com/.
    # Allow time for a leaked DIRECT fallback to become visible if one exists.
    time.sleep(14)
    page=content()
    save("unreachable-node-result")
    if "Example Domain" in page:
        raise AssertionError("CRITICAL: Gecko loaded an external page with unreachable VLESS node (potential DIRECT leak)")
    if "VLESS 本地代理运行中" not in page and "代理已断开" not in page:
        raise AssertionError("Browser no longer reports VLESS proxy mode")
    print("PASS: with unreachable VLESS node Gecko did not show the external Example Domain page",flush=True)
    print("NOTE: a single URL does not prove absence of ALL possible DNS/UDP leaks",flush=True)

if __name__=="__main__":
    try:run()
    except Exception:
        traceback.print_exc()
        try:save("failure")
        except Exception:pass
        try:(out/"logcat.txt").write_text(m.adb("logcat","-d","-t","1600",checked=False),encoding="utf8")
        except Exception:pass
        sys.exit(1)
