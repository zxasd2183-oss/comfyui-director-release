#!/usr/bin/env python3
"""Real GeckoView two-profile HTTP cookie isolation test using public httpbin.
Only tests cookie separation; no production changes, credentials or identity logins.
"""
import importlib.util
import pathlib
import sys
import time
import traceback

source=pathlib.Path("scripts/glacier_android_ci_smoke.py")
spec=importlib.util.spec_from_file_location("glacier_core_ui",source)
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
base=pathlib.Path("glacier-android-gecko/build/reports/cookie-isolation")
base.mkdir(parents=True,exist_ok=True)

def page_text():
    # Address bar is omitted to prevent false positives from the requested URL.
    return "\n".join(n.attrib.get("text","") for n in core.ui()
                     if n.attrib.get("class") not in
                     ("android.widget.EditText","android.widget.Button"))

def wait_content(words,timeout=35):
    until=time.monotonic()+timeout
    last=""
    while time.monotonic()<until:
        last=page_text()
        if all(w in last for w in words):
            return last
        time.sleep(2)
    raise AssertionError("Gecko content missing expected markers: "+repr(words)+"; seen "+repr(last[-500:]))

def save(label):
    try:
        core.adb("shell","screencap","-p","/sdcard/glacier-cookie.png",timeout=12)
        core.adb("pull","/sdcard/glacier-cookie.png",str(base/(label+".png")),timeout=12)
    except Exception as e:
        print("Screenshot not available:",repr(e),flush=True)
    try:
        core.adb("shell","uiautomator","dump","/sdcard/glacier-cookie.xml",timeout=20,checked=False)
        core.adb("pull","/sdcard/glacier-cookie.xml",str(base/(label+".xml")),timeout=12,checked=False)
    except Exception:
        pass

def run():
    print("=== GeckoView persistent-context COOKIE ISOLATION PROBE ===",flush=True)
    core.adb("install","-r",core.APK,timeout=150)
    core.adb("shell","pm","clear",core.PKG)
    core.adb("shell","am","start","-W","-n",core.PKG+"/.MainActivity",timeout=40)
    core.tap("明确使用直连")
    core.wait_for("私人空间",60)
    core.alive()
    print("Testing private profile cookie write",flush=True)
    core.type_url("https://httpbin.org/cookies/set?glacierci=private001")
    private=wait_content(["cookies","private001"])
    save("private-cookie")
    print("PASS: private-context cookie readable by the site",flush=True)

    print("Testing work context has NO private cookie",flush=True)
    core.tap("私人空间")
    core.tap("工作空间 · 独立 Cookie")
    core.wait_for("工作空间")
    core.type_url("https://httpbin.org/cookies")
    work=wait_content(["cookies"])
    if "private001" in work:
        raise AssertionError("COOKIE ISOLATION FAILURE: work sees private001")
    save("work-no-private-cookie")
    print("PASS: work context did not receive private cookie",flush=True)

    print("Testing work context cookie persists in work only",flush=True)
    core.type_url("https://httpbin.org/cookies/set?glacierci=work002")
    work=wait_content(["cookies","work002"])
    if "private001" in work:
        raise AssertionError("COOKIE ISOLATION FAILURE: work has both private and work cookies")
    save("work-own-cookie")
    print("PASS: work context has its own cookie",flush=True)

    core.tap("工作空间")
    core.tap("私人空间 · 独立 Cookie")
    core.wait_for("私人空间")
    core.type_url("https://httpbin.org/cookies")
    private=wait_content(["cookies","private001"])
    if "work002" in private:
        raise AssertionError("COOKIE ISOLATION FAILURE: private sees work002")
    save("private-no-work-cookie")
    print("PASS: returning to private context restores its own cookie only",flush=True)
    print("PASS: REAL cookie isolation validated in GeckoView across identity contexts",flush=True)

if __name__=="__main__":
    try:run()
    except Exception:
        traceback.print_exc()
        try:save("failure")
        except Exception:pass
        try:(base/"logcat.txt").write_text(core.adb("logcat","-d","-t","2000",checked=False),encoding="utf8")
        except Exception:pass
        sys.exit(1)
