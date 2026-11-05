#!/usr/bin/env python3
"""Bounded emulator UI smoke. URL bar updates are not proof of webpage rendering."""
import json, os, re, subprocess, sys, time, traceback
import xml.etree.ElementTree as ET
from pathlib import Path

OUT=Path(os.environ.get("GLACIER_SMOKE_OUT","emulator-evidence"))
OUT.mkdir(parents=True,exist_ok=True)
APK=os.environ["GLACIER_APK"]
PKG="cn.borealos.glacier.geckopreview"
checks=[]

def cmd(args,timeout=25):
    try:
        p=subprocess.run(args,capture_output=True,text=True,errors="replace",timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("ADB_TIMEOUT: "+" ".join(args))
    if p.returncode:
        raise RuntimeError("COMMAND_FAILED: "+" ".join(args)+" "+p.stderr[-400:])
    return p.stdout

def adb(*args,timeout=25):
    return cmd(["adb",*args],timeout)

def record(name,detail):
    checks.append({"step":name,"result":"observed","detail":detail})
    print("OBSERVED",name,detail,flush=True)

def dump():
    adb("shell","uiautomator","dump","/sdcard/glacier-smoke.xml",timeout=35)
    return ET.fromstring(adb("exec-out","cat","/sdcard/glacier-smoke.xml",timeout=20))

def lookup(root,text=None,desc=None,cls=None):
    for el in root.iter("node"):
        a=el.attrib
        if text is not None and a.get("text")!=text: continue
        if desc is not None and a.get("content-desc")!=desc: continue
        if cls is not None and a.get("class")!=cls: continue
        return a
    return None

def await_ui(timeout=60,**find):
    end=time.monotonic()+timeout
    last=""
    while time.monotonic()<end:
        try:
            node=lookup(dump(),**find)
            if node: return node
        except Exception as e: last=str(e)
        time.sleep(3)
    raise RuntimeError("UI_NOT_FOUND: "+str(find)+" "+last)

def tap(**find):
    a=await_ui(**find)
    m=re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",a.get("bounds",""))
    if not m: raise RuntimeError("BAD_BOUNDS: "+str(a))
    x1,y1,x2,y2=map(int,m.groups())
    # Never automatically replay non-idempotent taps after a timeout.
    adb("shell","input","tap",str((x1+x2)//2),str((y1+y2)//2),timeout=12)

def urlbar(prefix,timeout=75):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            a=lookup(dump(),cls="android.widget.EditText")
            if a and a.get("text","").startswith(prefix): return
        except Exception: pass
        time.sleep(3)
    raise RuntimeError("URL_BAR_NOT_CONFIRMED: "+prefix)

def page_event(site, timeout=100):
    """Gecko page-stop result, not an HTTP status or visible content check."""
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        data=adb("logcat","-d","-s","GlacierSmoke:I",timeout=25)
        if "PAGE_STOP site="+site+" success=true" in data:
            return
        if "PAGE_STOP site="+site+" success=false" in data:
            raise RuntimeError("GECKO_PAGE_LOAD_ERROR: "+site)
        time.sleep(5)
    raise RuntimeError("GECKO_PAGE_STOP_MISSING: "+site)

def shot(name):
    try:
        with (OUT/(name+".png")).open("wb") as f:
            subprocess.run(["adb","exec-out","screencap","-p"],stdout=f,timeout=25,check=True)
    except Exception as e: print("Screenshot unavailable:",e,flush=True)

def collect():
    for name,args in [
        ("logcat.txt",["logcat","-d","-t","8000"]),
        ("activity.txt",["shell","dumpsys","activity","activities"]),
        ("meminfo.txt",["shell","dumpsys","meminfo",PKG])
    ]:
        try: (OUT/name).write_text(adb(*args,timeout=25),encoding="utf-8")
        except Exception as e: (OUT/(name+".error")).write_text(str(e))
    shot("final")
    (OUT/"result.json").write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding="utf-8")

def main():
    if not Path(APK).is_file(): raise RuntimeError("APK missing")
    adb("wait-for-device",timeout=90)
    record("android_api",adb("shell","getprop","ro.build.version.sdk").strip())
    adb("install","-r",APK,timeout=180)
    record("apk_install","installed")
    adb("logcat","-c")
    adb("shell","am","start","-W","-n",PKG+"/.MainActivity",timeout=75)
    tap(text="明确使用直连")
    await_ui(desc="内核测试菜单",timeout=120)
    record("browser_start","UI present; Gecko page content NOT proven")
    insets_log=adb("logcat","-d","-s","GlacierSmoke:I",timeout=25)
    if not re.search(r"SYSTEM_BAR_INSETS top=[1-9]\\d* bottom=[1-9]\\d*",insets_log):
        raise RuntimeError("ANDROID_15_SYSTEM_BAR_INSETS_NOT_APPLIED")
    record("system_bar_insets","nonzero top and bottom reported by Android app")
    shot("01-start")
    urlbar("https://example.com")
    page_event("example")
    record("example_navigation","Gecko PAGE_STOP true; HTTP content not verified")
    shot("01-example-loaded")
    # Keep UI controls, background restore and identity switching ahead of
    # heavy external pages, so one emulator stall does not hide their results.
    tap(desc="新建标签页")
    await_ui(text="2")
    shot("02-tabs")
    record("new_tab","tab counter observed; tab persistence not verified")
    tap(text="私人空间  ▾")
    tap(text="工作空间 · 独立 Cookie")
    await_ui(text="工作空间  ▾")
    record("profile_switch","profile UI observed; Cookie isolation unverified")
    shot("02-work")
    adb("shell","input","keyevent","KEYCODE_HOME",timeout=12)
    adb("shell","am","start","-W","-n",PKG+"/.MainActivity",timeout=65)
    await_ui(desc="内核测试菜单")
    record("background_restore","browser UI available")
    shot("03-restored")
    tap(desc="内核测试菜单")
    tap(text="打开 ChatGPT")
    urlbar("https://chatgpt.com",timeout=100)
    page_event("chatgpt")
    record("chatgpt_navigation","Gecko PAGE_STOP true; login and site rendering not verified")
    shot("04-chatgpt")
    # GitHub last: in the earlier Google APIs emulator, accessibility and
    # screenshots stopped responding after this heavier page completed.
    tap(desc="内核测试菜单")
    tap(text="打开 GitHub")
    urlbar("https://github.com")
    page_event("github")
    record("github_navigation","Gecko PAGE_STOP true; HTTP content not verified")
    shot("05-github")
    print("UI_SMOKE_DONE; real web content, VLESS, cookies, files NOT VERIFIED",flush=True)

if __name__=="__main__":
    status=0
    try: main()
    except Exception as e:
        status=1
        checks.append({"step":"failure","result":"failed","detail":str(e)})
        traceback.print_exc()
        print("SMOKE_FAILED; cannot conclude GeckoView itself failed",flush=True)
    finally: collect()
    sys.exit(status)
