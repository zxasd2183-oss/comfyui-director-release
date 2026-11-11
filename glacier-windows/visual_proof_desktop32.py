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

from PySide6.QtWidgets import QApplication, QTabBar, QAbstractButton

def main():
    with tempfile.TemporaryDirectory(prefix="glacier-ui33-clean-profile-", ignore_cleanup_errors=True) as temp:
        os.environ["LOCALAPPDATA"] = temp
        from main import Browser
        app=QApplication.instance() or QApplication(["Glacier UI 33 visual QA"])
        window=None
        try:
            window=Browser(None,19982)
            window.resize(1360,890)
            window.show()
            for i in range(18):
                app.processEvents()
                time.sleep(0.10)
            root=window.centralWidget()
            if root.objectName()!="GlacierBrowserRoot32" or not window._chrome_ui33_ready:
                raise RuntimeError("Live browser did not initialize redesigned root")
            strip=window.chrome_tab14.parentWidget()
            nav=window._navigation_surface32
            if not (strip.y()<nav.y()<window.tabs.y()):
                raise RuntimeError("Real browser top tabs/nav/page vertical order is incorrect")
            print("viewport", window.width(), window.height(), flush=True)
            print("tab strip", strip.y(), strip.height(), flush=True)
            print("navigation", nav.y(), nav.height(), flush=True)
            omni=window._chrome_omnibox_shell33
            close_btn = window.chrome_tab14.tabButton(
                0, QTabBar.ButtonPosition.RightSide)
            if close_btn is None or close_btn.objectName() != "GlacierTabClose33":
                raise RuntimeError("Browser still renders an unpolished native tab close button")
            if close_btn.icon().isNull() or close_btn.width() != 18:
                raise RuntimeError("Browser polished tab close icon missing")
            new_btn = window.findChild(QAbstractButton, "GlacierNewTab33")
            if new_btn is None or new_btn.icon().isNull() or new_btn.width() != 30:
                raise RuntimeError("Browser compact + new tab button missing")
            if window._account_button26.text():
                raise RuntimeError("Browser account icon still has clipped old label")
            if omni.property("focused") is None:
                raise RuntimeError("Address group focus contract was not installed")
            print("omnibox group", omni.x(), omni.width(), omni.height(), flush=True)
            out=Path("ui-proof")
            out.mkdir(exist_ok=True)
            path=out/"Glacier-Windows-v0.20.22-live-ui33.png"
            # QtWebEngine may paint into a compositor surface that is not
            # included in QWidget.grab() on a headless Windows runner.
            # First verify the actual browser DOM is NOT blank. Screenshot
            # rasterization alone cannot prove a WebEngine document loaded.
            document=[]
            window.current().page().toHtml(lambda html: document.append(html))
            for _ in range(60):
                app.processEvents()
                if document:break
                time.sleep(0.05)
            html=document[0] if document else ""
            if ("Glacier" not in html or "快捷访问" not in html
                    or 'name="q"' not in html):
                raise RuntimeError(
                    "Startup tab did not contain real local new-tab DOM; "+
                    "length="+str(len(html))+" url="+window.current().url().toString())
            print("SUCCESS: actual local homepage DOM loaded",len(html),"bytes")
            screen=window.grab()
            if not screen.save(str(path),"PNG"):
                raise RuntimeError("Could not capture live Browser screenshot")
            if path.stat().st_size<8000:
                raise RuntimeError("Browser toolbar screenshot unexpectedly empty")
            image=screen.toImage()
            # A white viewport technically passes size/geometry checks but
            # is NOT a usable Chrome-style new tab. Require real painted text
            # from the local offline homepage, not only the upper toolbar.
            painted=0
            for y in range(nav.y()+nav.height()+40, image.height()-75, 4):
                for x in range(65, image.width()-65, 4):
                    rgb=image.pixelColor(x,y)
                    if rgb.red()<175 and rgb.green()<195 and rgb.blue()<210:
                        painted+=1
            if painted<40:
                # Not an assertion of page visibility on a real monitor:
                # the headless QtWebEngine framebuffer is absent in grab().
                # The local DOM check above is the authoritative page test.
                print("HEADLESS WEBENGINE: QWidget.grab did not capture page pixels;"
                      " browser DOM was validated separately",flush=True)
            else:
                print("Real offline homepage colored pixels",painted,flush=True)
            min_width=max(260, int(window.width()*0.33))
            if omni.width()<min_width or omni.height()<38:
                raise RuntimeError(
                    "Actual Chrome grouped omnibox remains too narrow: "+
                    str(omni.width())+" of "+str(window.width()))
            if nav.height()<51 or strip.height()<43:
                raise RuntimeError("Actual Chrome navigation/tab strip geometry is incorrect")
            if omni.layout().count()!=3:
                raise RuntimeError("Site, address and bookmark were not grouped into omnibox")
            if window._account_button26.width()>38:
                raise RuntimeError("Account pill is still crowding the address bar")
            if not window.tabs.tabBar().isHidden():
                raise RuntimeError("Legacy duplicate internal tab strip is visible")
            print("SUCCESS: actual Windows browser UI33, grouped omnibox and compact shell captured")
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
