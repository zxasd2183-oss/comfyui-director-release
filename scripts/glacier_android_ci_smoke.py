#!/usr/bin/env python3
"""Android emulator smoke test of the actual GeckoView + sing-box experiment.

This script drives the published app UI, NOT a WebView stand-in.
It asserts startup, explicit DIRECT gate, URL navigation, tab lifecycle,
profile switching and process survival. It does not claim:
- real VLESS tunnel success without a test server/credentials
- cookie isolation, upload/download, or sites' auth success
- render correctness merely from an address bar location update
"""
import pathlib
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

PKG="cn.borealos.glacier.geckopreview"
BASE=pathlib.Path("glacier-android-gecko/build/reports/core-smoke")
BASE.mkdir(parents=True,exist_ok=True)
APK="glacier-android-gecko/app/build/outputs/apk/debug/app-debug.apk"

def adb(*args,timeout=30,checked=True):
    p=subprocess.run(["adb",*args],capture_output=True,text=True,timeout=timeout)
    if checked and p.returncode:
        raise AssertionError(f"adb {args[0]} failed rc={p.returncode}: {p.stderr[-500:]}")
    return p.stdout

def snapshot(label):
    adb("shell","screencap","-p","/sdcard/glacier-ci.png",timeout=20)
    adb("pull","/sdcard/glacier-ci.png",str(BASE/(label+".png")),timeout=30)
    adb("shell","uiautomator","dump","/sdcard/glacier-ui.xml",timeout=35,checked=False)
    adb("pull","/sdcard/glacier-ui.xml",str(BASE/(label+".xml")),timeout=30,checked=False)

def ui():
    last=""
    for attempt in range(6):
        adb("shell","uiautomator","dump","/sdcard/glacier-ui.xml",timeout=35,checked=False)
        p=subprocess.run(["adb","shell","cat","/sdcard/glacier-ui.xml"],
                         capture_output=True,text=True,timeout=12)
        last=p.stdout
        try:
            root=ET.fromstring(last)
            return list(root.iter("node"))
        except ET.ParseError:
            time.sleep(1.5)
    raise AssertionError("UI automation returned invalid XML "+last[:100])

def locate(needle, mode="contains"):
    nodes=ui()
    for node in nodes:
        d=node.attrib
        a=(d.get("text","") or "")+" "+(d.get("content-desc","") or "")
        if ((needle in a) if mode=="contains" else (needle==a.strip())):
            m=re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",d.get("bounds",""))
            if m:
                x1,y1,x2,y2=map(int,m.groups())
                if x2>x1 and y2>y1:
                    return ((x1+x2)//2,(y1+y2)//2)
    return None

def wait_for(label,seconds=28):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        p=locate(label)
        if p:return p
        time.sleep(1.6)
    snapshot("failed-"+re.sub("[^a-z0-9]+","-",label.lower()))
    raise AssertionError(f"UI text not found: {label}")

def tap(label):
    x,y=wait_for(label)
    adb("shell","input","tap",str(x),str(y))
    time.sleep(1)

def alive():
    text=adb("shell","pidof",PKG,checked=False).strip()
    if not text:
        snapshot("crashed")
        raise AssertionError("Glacier app process is not alive")
    return text

def type_url(value):
    pos=locate("搜索或输入网址")
    if pos is None:
        nodes=ui()
        for n in nodes:
            if n.attrib.get("class")=="android.widget.EditText":
                m=re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",n.attrib.get("bounds",""))
                if m:
                    a=list(map(int,m.groups()));pos=((a[0]+a[2])//2,(a[1]+a[3])//2)
                    break
    if pos is None:
        raise AssertionError("Address EditText not present")
    adb("shell","input","tap",str(pos[0]),str(pos[1]))
    time.sleep(0.3)
    # URL input is ASCII and does not rely on keyboard IME.
    adb("shell","input","text",value,timeout=18)
    adb("shell","input","keyevent","KEYCODE_ENTER")
    time.sleep(5)
    alive()

def main():
    print("=== GLACIER ACTUAL ANDROID EMULATOR SMOKE TEST ===",flush=True)
    print(adb("shell","getprop","ro.build.version.release").strip())
    print("ABI",adb("shell","getprop","ro.product.cpu.abi").strip(),flush=True)
    print("Installing actual GeckoView/sing-box APK",flush=True)
    adb("install","-r",APK,timeout=180)
    adb("shell","pm","clear",PKG)
    print("Launching and choosing explicit DIRECT mode",flush=True)
    adb("shell","am","start","-W","-n",PKG+"/.MainActivity",timeout=35)
    tap("明确使用直连")
    wait_for("私人空间",seconds=60)
    alive()
    snapshot("01-home")
    print("PASS: native GeckoView UI initialized after explicit DIRECT gate",flush=True)

    tap("新建标签页")
    # content description in bottom plus may be detected by accessibility.
    if locate("2",mode="exact") is None:
        snapshot("second-tab-count-failure")
        raise AssertionError("Tab count was not 2 after opening second tab")
    alive()
    snapshot("03-second-tab")
    print("PASS: new GeckoView tab survived",flush=True)
    print(adb("shell","dumpsys","meminfo",PKG,timeout=20,checked=False)[-2200:],flush=True)

    tap("私人空间")
    tap("工作空间 · 独立 Cookie")
    wait_for("工作空间",seconds=30)
    alive()
    snapshot("04-work-profile")
    print("PASS: identity-space transition created work GeckoSession",flush=True)

    tap("工作空间")
    tap("私人空间 · 独立 Cookie")
    wait_for("私人空间",seconds=30)
    alive()
    snapshot("05-back-private")
    print("PASS: switched back to private context",flush=True)

    # Exercise app process through Android HOME/foreground navigation.
    adb("shell","input","keyevent","KEYCODE_HOME")
    time.sleep(2)
    adb("shell","am","start","-n",PKG+"/.MainActivity")
    time.sleep(3)
    alive()
    snapshot("06-after-background")
    print("PASS: background-to-foreground process survival",flush=True)

    # Navigate AFTER the UI/session checks so a heavy website cannot mask
    # independently verified tab/profile functionality.
    for i,url in enumerate(("https://example.com/","https://github.com/","https://chatgpt.com/")):
        print("Navigating",url,flush=True)
        type_url(url)
        snapshot("07-navigation-"+str(i))
        print("PASS: browser survived navigation command for "+url,flush=True)

    # Strict no-silent-direct policy is unit-tested separately;
    # actual proxy egress and DNS leak require an accessible VLESS test node.
    print("LIMITATION: no remote VLESS server, no cross-profile cookie assertion, no HTTP upload/download assertion",flush=True)

try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    try:
        snapshot("failure")
        (BASE/"logcat.txt").write_text(adb("logcat","-d","-t","2200",timeout=30,checked=False),encoding="utf-8")
    except Exception as e:
        print("Could not collect diagnostics:",str(e))
    sys.exit(1)
