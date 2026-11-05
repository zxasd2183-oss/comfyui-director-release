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

launcher_anrs = 0

def dump():
    global launcher_anrs
    adb("shell","uiautomator","dump","/sdcard/glacier-smoke.xml",timeout=35)
    root = ET.fromstring(adb("exec-out","cat","/sdcard/glacier-smoke.xml",timeout=20))
    # Only dismiss the emulator's own home-screen ANR. Never mask a Glacier
    # application ANR: a separate app failure remains a test failure.
    labels = {n.attrib.get("text","") for n in root.iter("node")}
    if ("Quickstep isn't responding" in labels
            or "Launcher3 isn't responding" in labels):
        launcher_anrs += 1
        if launcher_anrs > 2:
            raise RuntimeError("REPEATED_ANDROID_LAUNCHER_ANR")
        button = next((n.attrib for n in root.iter("node")
                       if n.attrib.get("text")=="Close app"), None)
        if button is None:
            raise RuntimeError("SYSTEM_LAUNCHER_ANR_NOT_DISMISSABLE")
        m=re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                       button.get("bounds",""))
        if not m:
            raise RuntimeError("SYSTEM_LAUNCHER_ANR_BAD_BUTTON_BOUNDS")
        x1,y1,x2,y2=map(int,m.groups())
        adb("shell","input","tap",str((x1+x2)//2),str((y1+y2)//2),timeout=12)
        record("system_launcher_anr","dismissed emulator Quickstep/Launcher3 only")
        time.sleep(2)
        adb("shell","uiautomator","dump","/sdcard/glacier-smoke.xml",timeout=35)
        root = ET.fromstring(adb("exec-out","cat","/sdcard/glacier-smoke.xml",timeout=20))
    return root

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

def isolation_state(marker,timeout=60):
    """Require real page-script markers, not merely that profile menu changed."""
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        log=adb("logcat","-d","-s","GlacierSmoke:I",timeout=20)
        if "ISOLATION_STATE=GLACIER_TEST_"+marker in log:
            return
        if "ISOLATION_STATE=GLACIER_TEST_WORK_LEAK" in log:
            raise RuntimeError("COOKIE_STORAGE_CROSS_PROFILE_LEAK")
        if "ISOLATION_STATE=GLACIER_TEST_PRIVATE_LOST" in log:
            raise RuntimeError("PRIVATE_PROFILE_STORAGE_NOT_RETAINED")
        time.sleep(2)
    raise RuntimeError("ISOLATION_MARKER_NOT_OBSERVED: "+marker)

def file_event(marker,timeout=60):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        log=adb("logcat","-d","-s","GlacierSmoke:I",timeout=20)
        if "FILE_EVENT="+marker in log:
            return
        time.sleep(2)
    raise RuntimeError("FILE_EVENT_MISSING: "+marker)

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
    adb("reverse","tcp:18765","tcp:18765",timeout=15)
    record("isolation_fixture_route","adb reverse loopback enabled")
    adb("logcat","-c")
    adb("shell","am","start","-W","-n",PKG+"/.MainActivity",timeout=75)
    tap(text="明确使用直连")
    await_ui(desc="内核测试菜单",timeout=120)
    record("browser_start","UI present; Gecko page content NOT proven")
    insets_log=adb("logcat","-d","-s","GlacierSmoke:I",timeout=25)
    if not re.search(r"SYSTEM_BAR_INSETS top=[1-9]\d* bottom=[1-9]\d*",insets_log):
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
    tap(desc="内核测试菜单")
    tap(text="隔离自测：私人写入")
    isolation_state("PRIVATE_SEEDED")
    record("private_storage_seed","cookie and localStorage written by JS on loopback fixture")
    tap(text="私人空间  ▾")
    tap(text="工作空间 · 独立 Cookie")
    await_ui(text="工作空间  ▾")
    tap(desc="内核测试菜单")
    tap(text="隔离自测：工作检查")
    isolation_state("WORK_ISOLATED")
    record("work_profile_isolation","work page observed neither private Cookie nor localStorage")
    shot("02-work")
    tap(text="工作空间  ▾")
    tap(text="私人空间 · 独立 Cookie")
    await_ui(text="私人空间  ▾")
    tap(desc="内核测试菜单")
    tap(text="隔离自测：私人复查")
    isolation_state("PRIVATE_RETAINED")
    record("private_storage_retained","private cookie and localStorage retained after switching")
    shot("03-private-retained")
    # Real Gecko HTML file controls -> Android Storage Access Framework.
    # No real accounts or sensitive documents; only cancel paths in the smoke
    # test until reliable file-byte round trips have been independently proven.
    tap(desc="内核测试菜单")
    tap(text="传输自测：打开测试页面")
    isolation_state("TRANSFER_READY")
    record("transfer_fixture","loopback Gecko transfer page loaded")
    tap(text="选择测试文件")
    file_event("UPLOAD_PICKER_OPEN")
    record("file_upload_prompt","Android document picker invoked from web file input")
    shot("03-upload-picker")
    adb("shell","input","keyevent","KEYCODE_BACK",timeout=12)
    file_event("UPLOAD_CANCELLED")
    record("file_upload_cancel","cancel resolved Gecko file prompt")
    tap(text="保存测试下载")
    file_event("DOWNLOAD_RESPONSE_RECEIVED")
    record("download_response","Gecko external-response callback saw fixture attachment")
    tap(text="继续")
    file_event("DOWNLOAD_STREAM_STAGED",timeout=90)
    record("download_stream","native response body staged, not re-fetched via Android DownloadManager")
    shot("03-save-picker")
    adb("shell","input","keyevent","KEYCODE_BACK",timeout=12)
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
    print("UI_SMOKE_DONE; Cookie/localStorage and transfer callbacks verified; login, VLESS exit and real file roundtrip NOT VERIFIED",flush=True)

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
