#!/usr/bin/env python3
"""Fresh-emulator real-site stress. Never substitutes for full UI regression."""
import sys
import traceback
from pathlib import Path
import emulator_smoke_v012 as smoke

def run():
    if not Path(smoke.APK).is_file():
        raise RuntimeError("APK_NOT_FOUND")
    smoke.adb("wait-for-device",timeout=90)
    smoke.adb("install","-r",smoke.APK,timeout=180)
    smoke.adb("logcat","-c")
    smoke.adb("shell","am","start","-W","-n",smoke.PKG+"/.MainActivity",timeout=75)
    smoke.tap(text="明确使用直连")
    bounds=smoke.await_ui(desc="更多选项",timeout=120)["bounds"]
    smoke.await_ui(desc="Glacier 地址栏",timeout=45)
    smoke.record("fresh_web_session","native toolbar available with explicit direct-network selection")
    smoke.shot("00-toolbar")
    smoke.tap(desc="更多选项")
    smoke.tap_menu_item("打开 ChatGPT")
    smoke.urlbar("https://chatgpt.com",timeout=110)
    smoke.page_event("chatgpt",timeout=110)
    smoke.record("chatgpt_navigation","Gecko page stop succeeded; login not verified")
    smoke.shot("01-chatgpt")
    smoke.tap(desc="更多选项")
    smoke.tap_menu_item("打开 GitHub")
    smoke.page_event("github",timeout=110)
    smoke.record("github_navigation","Gecko page stop succeeded; site content not verified")
    smoke.shot("02-github")
    # Both the Chromium/Gecko page-load event and an actual native input
    # response are required. PAGE_STOP alone cannot pass this test.
    smoke.assert_native_menu_responsive(bounds,timeout=35)
    smoke.shot("03-responsive-menu")
    print("WEB_STRESS_DONE",flush=True)

if __name__=="__main__":
    status=0
    try:run()
    except Exception as exc:
        status=1
        reason=type(exc).__name__+": "+str(exc)
        smoke.checks.append({"step":"failure","result":"failed","detail":reason})
        traceback.print_exc()
        print("::error title=Glacier independent web stress failed::"+reason,flush=True)
    finally:smoke.collect()
    sys.exit(status)
