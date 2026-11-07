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

def tap_menu_item(label):
    """Scroll Android's native overflow ListView, then tap exactly once.

    Longer Chrome-like menus can have inaccessible off-screen rows. Never
    replay the tap itself, only scroll until the intended item is visible.
    """
    for attempt in range(7):
        try:
            tap(text=label,timeout=5)
            return
        except RuntimeError as exc:
            if "UI_NOT_FOUND" not in str(exc):
                raise
        if attempt==6:
            break
        adb("shell","input","swipe","540","1550","540","580","350",timeout=14)
        time.sleep(1)
    raise RuntimeError("NATIVE_OVERFLOW_ITEM_NOT_FOUND: "+label)

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

def tap_any_text(labels, timeout=45):
    """Wait for one of a few known, Android-version-specific picker labels."""
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            root=dump()
            for label in labels:
                node=lookup(root,text=label)
                if node:
                    m=re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",node.get("bounds",""))
                    if m:
                        x1,y1,x2,y2=map(int,m.groups())
                        adb("shell","input","tap",str((x1+x2)//2),str((y1+y2)//2),timeout=12)
                        return label
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("ANDROID_DOCUMENT_PICKER_TARGET_NOT_FOUND: "+str(labels))

def install_fixture_upload():
    """Make an artificial file in Downloads for Android DocumentsUI."""
    file=OUT/"glacier-upload-test.txt"
    file.write_bytes(b"GLACIER_UPLOAD_TEST\n")
    adb("shell","mkdir","-p","/sdcard/Download",timeout=15)
    adb("push",str(file),"/sdcard/Download/glacier-upload-test.txt",timeout=40)
    try:
        adb("shell","am","broadcast","-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
            "-d","file:///sdcard/Download/glacier-upload-test.txt",timeout=15)
    except Exception:
        pass
    record("fixture_upload_prepared","only artificial local text file")

def choose_fixture_upload():
    """DocumentsUI Recent -> Downloads on a fixed Android 15 Pixel 6 AVD."""
    try:
        tap_any_text(["glacier-upload-test.txt"],timeout=10)
        return
    except RuntimeError:
        pass
    # The location is grounded by the prior run's DocumentsUI screenshot
    # (1080x2400 Pixel 6). This fallback stays restricted to the CI emulator.
    adb("shell","input","tap","55","148",timeout=12)
    tap_any_text(["Downloads","Download"],timeout=35)
    tap_any_text(["glacier-upload-test.txt"],timeout=45)

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
    await_ui(desc="更多选项",timeout=120)
    await_ui(desc="Glacier 地址栏",timeout=40)
    await_ui(desc="主页",timeout=40)
    await_ui(desc="标签页",timeout=40)
    record("m02_mobile_ui","Chrome-style single omnibox row, home, tabs and overflow visible")
    tap(desc="更多选项")
    tap_menu_item("更新与版本")
    await_ui(text="Glacier · 更新与版本 0.2.2",timeout=35)
    tap(text="检查更新")
    await_ui(text="未能检查更新",timeout=25)
    tap(text="知道了")
    record("m05_debug_update_gate","debug APK presents update UI but refuses online update requests")
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
    # M04: bookmark and history must work as actual interactive menu flows.
    tap(desc="更多选项")
    tap(text="收藏当前页面")
    end=time.monotonic()+35
    while time.monotonic()<end:
        bookmark_log=adb("logcat","-d","-s","GlacierSmoke:I",timeout=20)
        if "M04_BOOKMARK_ADDED=true" in bookmark_log:
            break
        if "M04_BOOKMARK_REJECTED=INVALID_PAGE" in bookmark_log:
            raise RuntimeError("M04_BOOKMARK_REJECTED_INVALID_PAGE")
        time.sleep(2)
    else:
        raise RuntimeError("M04_BOOKMARK_ACTION_NOT_CONFIRMED")
    tap(desc="更多选项")
    tap(text="书签")
    await_ui(text="私人空间 · 书签",timeout=35)
    record("m04_bookmark_menu","saved private bookmark is visible in native list")
    shot("01-m04-bookmarks")
    tap(text="关闭")
    tap(desc="更多选项")
    tap(text="历史记录")
    await_ui(text="私人空间 · 历史记录",timeout=35)
    record("m04_history_menu","private history list opened from live browser")
    tap(text="关闭")
    # Keep UI controls, background restore and identity switching ahead of
    # heavy external pages, so one emulator stall does not hide their results.
    tap(desc="更多选项")
    tap(text="新建标签页")
    await_ui(text="2")
    await_ui(text="常用网站")
    record("chrome_new_tab","native new-tab page and shortcuts visible")
    tap(desc="标签页")
    await_ui(text="标签页 · 2")
    shot("02-tab-grid")
    record("chrome_tab_grid","two-column tab overview opened")
    tap(desc="返回浏览器")
    record("new_tab","tab counter and new-tab page observed; tab persistence not verified")
    tap(desc="更多选项")
    tap_menu_item("内部测试工具")
    tap(text="隔离自测：私人写入")
    isolation_state("PRIVATE_SEEDED")
    record("private_storage_seed","cookie and localStorage written by JS on loopback fixture")
    tap(desc="更多选项")
    tap(text="切换账号空间")
    tap(text="工作空间 · 独立 Cookie")
    tap(desc="更多选项")
    tap_menu_item("内部测试工具")
    tap(text="隔离自测：工作检查")
    isolation_state("WORK_ISOLATED")
    record("work_profile_isolation","work page observed neither private Cookie nor localStorage")
    shot("02-work")
    tap(desc="更多选项")
    tap(text="切换账号空间")
    tap(text="私人空间 · 独立 Cookie")
    tap(desc="更多选项")
    tap_menu_item("内部测试工具")
    tap(text="隔离自测：私人复查")
    isolation_state("PRIVATE_RETAINED")
    record("private_storage_retained","private cookie and localStorage retained after switching")
    shot("03-private-retained")
    # M03: make one new tab in each account space, force-stop Android,
    # and prove both work/private survive a fresh process and runtime.
    tap(desc="更多选项")
    tap(text="切换账号空间")
    tap(text="工作空间 · 独立 Cookie")
    tap(desc="更多选项")
    tap(text="新建标签页")
    tap(desc="更多选项")
    tap(text="切换账号空间")
    tap(text="私人空间 · 独立 Cookie")
    tap(desc="更多选项")
    tap(text="新建标签页")
    await_ui(text="5",timeout=30)
    time.sleep(4)
    adb("shell","am","force-stop",PKG,timeout=15)
    # Clear old markers so M04 can only pass if the restarted process
    # genuinely reloads the encrypted bookmark/history database.
    adb("logcat","-c",timeout=15)
    adb("shell","am","start","-W","-n",PKG+"/.MainActivity",timeout=75)
    tap(text="明确使用直连")
    await_ui(desc="更多选项",timeout=120)
    await_ui(text="3",timeout=45)
    restore_log=adb("logcat","-d","-s","GlacierSmoke:I",timeout=20)
    if "TAB_RESTORE_COUNT=3" not in restore_log:
        raise RuntimeError("M03_TABS_NOT_RESTORED")
    tap(desc="标签页")
    await_ui(text="标签页 · 3",timeout=40)
    await_ui(text="工作 · about:blank",timeout=40)
    await_ui(text="私人 · about:blank",timeout=40)
    end=time.monotonic()+25
    saved_url=False
    while time.monotonic()<end:
        root=dump()
        if any(n.attrib.get("text","").startswith("私人 · https://example.com")
               for n in root.iter("node")):
            saved_url=True
            break
        time.sleep(2)
    if not saved_url:
        raise RuntimeError("M03_SAVED_HTTPS_URL_LOST")
    record("m03_url_restored","saved HTTPS URL retained after process death")
    record("m03_force_stop_restore","three tabs across both profiles restored after process death")
    shot("03-restored-tab-grid")
    tap(desc="返回浏览器")
    tap(desc="更多选项")
    tap(text="书签")
    await_ui(text="私人空间 · 书签",timeout=30)
    m04_log=adb("logcat","-d","-s","GlacierSmoke:I",timeout=20)
    if "M04_LIBRARY_LIST kind=bookmarks profile=private count=1" not in m04_log:
        raise RuntimeError("M04_BOOKMARK_NOT_PERSISTED")
    record("m04_bookmark_persisted","private bookmark survived Android force-stop")
    tap(text="关闭")
    tap(desc="更多选项")
    tap(text="历史记录")
    await_ui(text="私人空间 · 历史记录",timeout=30)
    m04_log=adb("logcat","-d","-s","GlacierSmoke:I",timeout=20)
    if not re.search(r"M04_LIBRARY_LIST kind=history profile=private count=[1-9][0-9]*",m04_log):
        raise RuntimeError("M04_HISTORY_NOT_PERSISTED")
    record("m04_history_persisted","private history reopened after force-stop")
    tap(text="关闭")
    # Real Gecko HTML file controls -> Android Storage Access Framework.
    # No real accounts or sensitive documents; only cancel paths in the smoke
    # test until reliable file-byte round trips have been independently proven.
    tap(desc="更多选项")
    tap_menu_item("内部测试工具")
    tap(text="传输自测：打开测试页面")
    isolation_state("TRANSFER_READY")
    record("transfer_fixture","loopback Gecko transfer page loaded")
    install_fixture_upload()
    tap(text="选择测试文件")
    file_event("UPLOAD_PICKER_OPEN")
    record("file_upload_prompt","Android document picker invoked from web file input")
    shot("03-upload-picker")
    choose_fixture_upload()
    file_event("UPLOAD_SELECTION_CONFIRMED")
    isolation_state("UPLOAD_OK",timeout=90)
    record("file_upload_bytes","actual fake text file was sent via Gecko POST and verified byte-for-byte by loopback server")
    shot("03-upload-roundtrip")
    tap(text="保存测试下载")
    file_event("DOWNLOAD_RESPONSE_RECEIVED")
    record("download_response","Gecko external-response callback saw fixture attachment")
    tap(text="继续")
    file_event("DOWNLOAD_STREAM_STAGED",timeout=90)
    record("download_stream","native response body staged, not re-fetched via Android DownloadManager")
    shot("03-save-picker")
    tap_any_text(["SAVE","Save","Save file"],timeout=35)
    file_event("DOWNLOAD_SAVED",timeout=90)
    saved=adb("exec-out","cat","/sdcard/Download/glacier-download-test.txt",timeout=35)
    if saved != "GLACIER_DOWNLOAD_TEST\n":
        raise RuntimeError("DOWNLOADED_FILE_BYTES_MISMATCH")
    record("file_download_bytes","saved Android Downloads file matched full Gecko response body, byte-for-byte")
    shot("03-download-saved")
    tap(desc="更多选项")
    tap(text="下载记录")
    await_ui(text="私人空间 · 下载记录",timeout=35)
    log_m04=adb("logcat","-d","-s","GlacierSmoke:I",timeout=20)
    if "M04_DOWNLOAD_RECORDED=true" not in log_m04 or "M04_LIBRARY_LIST kind=downloads profile=private count=1" not in log_m04:
        raise RuntimeError("M04_DOWNLOAD_RECORD_NOT_SAVED")
    record("m04_download_record","download SAF destination recorded in current private space")
    shot("03-m04-download-history")
    tap(text="关闭")
    adb("shell","input","keyevent","KEYCODE_HOME",timeout=12)
    adb("shell","am","start","-W","-n",PKG+"/.MainActivity",timeout=65)
    await_ui(desc="更多选项")
    record("background_restore","browser UI available")
    shot("03-restored")
    tap(desc="更多选项")
    tap_menu_item("打开 ChatGPT")
    urlbar("https://chatgpt.com",timeout=100)
    page_event("chatgpt")
    record("chatgpt_navigation","Gecko PAGE_STOP true; login and site rendering not verified")
    shot("04-chatgpt")
    # GitHub last: in the earlier Google APIs emulator, accessibility and
    # screenshots stopped responding after this heavier page completed.
    tap(desc="更多选项")
    tap_menu_item("打开 GitHub")
    await_ui(desc="Glacier 地址栏",timeout=35)
    page_event("github")
    record("github_navigation","Gecko PAGE_STOP true; HTTP content not verified")
    shot("05-github")
    print("UI_SMOKE_DONE; Cookie/localStorage and transfer callbacks verified; login and VLESS real exit NOT VERIFIED",flush=True)

if __name__=="__main__":
    status=0
    try: main()
    except Exception as e:
        status=1
        reason=f"{type(e).__name__}: {e}"
        checks.append({"step":"failure","result":"failed","detail":reason})
        traceback.print_exc()
        # GitHub shows this in the run's Annotations even without job logs.
        annotation=reason.replace("%","%25").replace("\r","%0D").replace("\n","%0A")
        print(f"::error title=Glacier Android UI smoke failed::{annotation}",flush=True)
        summary=os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            try:
                completed=[str(c["step"]) for c in checks if c.get("result")=="observed"]
                with open(summary,"a",encoding="utf-8") as out:
                    out.write("\n### Glacier Android M05 UI smoke — FAILED\n\n")
                    out.write("**Failure:** `"+reason.replace("`","'")+"`\n\n")
                    out.write("**Completed checks:** "+(", ".join(completed) if completed else "none")+"\n")
                    out.write("\nEvidence artifact: `GlacierAndroid-v0.2.2-M05-emulator-evidence`\n")
            except OSError as summary_error:
                print("Could not write smoke summary:",type(summary_error).__name__,flush=True)
        print("SMOKE_FAILED; cannot conclude GeckoView itself failed",flush=True)
    finally: collect()
    sys.exit(status)
