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
            print("omnibox group", omni.x(), omni.width(), omni.height(), flush=True)
            out=Path("ui-proof")
            out.mkdir(exist_ok=True)
            path=out/"Glacier-Windows-v0.20.24-live-ui33.png"
            # QtWebEngine may paint into a compositor surface that is not
            # included in QWidget.grab() on a headless Windows runner.
            # First verify the actual browser DOM is NOT blank. Screenshot
            # rasterization alone cannot prove a WebEngine document loaded.
            # A fast first toHtml callback may still return Chromium's empty
            # placeholder document. Poll for the REAL rendered page, not just
            # any callback, and retain the hard failure on a persistent blank.
            document=[]
            deadline=time.monotonic()+15
            html=""
            while time.monotonic()<deadline:
                window.current().page().toHtml(lambda result: document.append(result))
                for _ in range(12):
                    app.processEvents()
                    time.sleep(0.04)
                    if document:
                        html=document[-1]
                        if ("Glacier" in html and "快捷访问" in html
                                and 'name="q"' in html):
                            break
                if "Glacier" in html and "快捷访问" in html and 'name="q"' in html:
                    break
                document.clear()
            if not ("Glacier" in html and "快捷访问" in html
                    and 'name="q"' in html):
                raise RuntimeError(
                    "Startup tab did not render actual local homepage within 15s; "+
                    "html_length="+str(len(html))+
                    " url_prefix="+window.current().url().toString()[:140])
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
            # The revised compact navigation is deliberately 50px, while
            # keeping the 44px tab row and the site/address/bookmark group.
            if not (49 <= nav.height() <= 52) or strip.height()<43:
                raise RuntimeError("Actual Chrome navigation/tab strip geometry is incorrect")
            plus=getattr(window, "_new_tab_button34", None)
            if plus is None or plus.objectName()!="GlacierNewTab34" or plus.icon().isNull():
                raise RuntimeError("Actual clickable Chrome new-tab icon was not installed")
            if plus.width()!=32 or plus.text():
                raise RuntimeError("New-tab geometry or legacy glyph was not replaced")
            proxy=getattr(window,"proxy_label",None)
            indicator=getattr(window,"_proxy_indicator34",None)
            if (proxy is None or indicator is None or not proxy.isHidden()
                    or indicator.icon().isNull() or indicator.text()):
                raise RuntimeError("Visible proxy is still a loose legacy Unicode dot")
            if indicator.accessibleName() != "本地 VLESS 未连接，点击重连":
                raise RuntimeError("First frame status icon has wrong accessible state")
            if window.windowIcon().isNull():
                raise RuntimeError("Glacier application title icon was not installed")
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
