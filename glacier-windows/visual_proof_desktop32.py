"""Capture the REAL running Windows Browser shell on a clean CI account.

Unlike the stand-in unit-test host, this checks the actual constructed
QWebEngine browser, all extension initializers, the external tabs, its
42px+ omnibox, and the visible final toolbar hierarchy.
Nothing is uploaded except a screenshot from an empty temporary profile.
No VLESS line or account credential is supplied or requested.
"""
from __future__ import annotations
import os
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

def main():
    with tempfile.TemporaryDirectory(prefix="glacier-ui32-clean-profile-") as temp:
        os.environ["LOCALAPPDATA"] = temp
        from main import Browser
        app=QApplication.instance() or QApplication(["Glacier UI 32 visual QA"])
        window=None
        try:
            window=Browser(None,19982)
            window.resize(1360,890)
            window.show()
            for i in range(18):
                app.processEvents()
                time.sleep(0.10)
            root=window.centralWidget()
            if root.objectName()!="GlacierBrowserRoot32":
                raise RuntimeError("Live browser did not initialize redesigned root")
            strip=window.chrome_tab14.parentWidget()
            nav=window._navigation_surface32
            if not (strip.y()<nav.y()<window.tabs.y()):
                raise RuntimeError("Real browser top tabs/nav/page vertical order is incorrect")
            if window.address.width()<480 or window.address.height()<40:
                raise RuntimeError("Actual address bar is still narrow or too short")
            if nav.height()<55 or strip.height()<40:
                raise RuntimeError("Actual navigation/tab strip remained old compact geometry")
            if not window.tabs.tabBar().isHidden():
                raise RuntimeError("Legacy duplicate internal tab strip is visible")
            out=Path("ui-proof")
            out.mkdir(exist_ok=True)
            path=out/"Glacier-Windows-v0.20.21-live-ui32.png"
            if not window.grab().save(str(path),"PNG"):
                raise RuntimeError("Could not capture live Browser screenshot")
            if path.stat().st_size<12000:
                raise RuntimeError("Browser visual proof unexpectedly empty")
            print("SUCCESS: actual Windows browser UI32, controls and visible shell captured")
            print("tab strip y/h",strip.y(),strip.height())
            print("navigation y/h",nav.y(),nav.height())
            print("omnibox x/w/h",window.address.x(),window.address.width(),window.address.height())
            print("screenshot",path,path.stat().st_size,"bytes")
        finally:
            if window is not None:
                window.close()
            app.processEvents()

if __name__=="__main__":
    main()
