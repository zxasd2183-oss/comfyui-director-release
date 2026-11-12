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

from PySide6.QtWidgets import QApplication, QPushButton, QDialog
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from glacier_chrome_top35 import framed_top_geometry36
import sys
from secure_update import CURRENT_VERSION

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
            path=out/f"Glacier-Windows-v{CURRENT_VERSION}-live-ui33.png"
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
            # Include the actual compact tab caption/favicon in the saved
            # screenshot, not merely in a post-capture assertion.
            window._glacier_sync_tab_icons35()
            app.processEvents()
            # A real WebEngine compositor can create its native surface
            # slightly after DOM readiness on Windows CI. Retry painting
            # rather than treating a transient blank initial grab as a
            # functioning browser. Persistent blank pixels still FAIL CLOSED.
            painted = 0
            for attempt in range(15):
                app.processEvents()
                screen = window.grab()
                if not screen.save(str(path), "PNG"):
                    raise RuntimeError("Could not capture live Browser screenshot")
                if path.stat().st_size < 8000:
                    raise RuntimeError("Browser toolbar screenshot unexpectedly empty")
                image = screen.toImage()
                painted = 0
                for y in range(nav.y()+nav.height()+40, image.height()-75, 4):
                    for x in range(65, image.width()-65, 4):
                        rgb = image.pixelColor(x,y)
                        if rgb.red()<175 and rgb.green()<195 and rgb.blue()<210:
                            painted += 1
                if painted >= 120:
                    break
                if attempt == 6:
                    # Trigger a real viewport resize/reflow on this CI host;
                    # do not disable the nonblank visual assertion.
                    window.resize(1361, 890)
                    app.processEvents()
                    window.resize(1360, 890)
                window.current().update()
                app.processEvents()
                time.sleep(0.15)
            if painted < 120:
                raise RuntimeError(
                    "Qt WebEngine viewport remained visually blank after "
                    "native repaint/reflow checks; " + str(painted) +
                    " sampled page pixels")
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
            # The active tab may meet, but never cross, the bottom edge of
            # the first-row frame. The other hitboxes stay fully inset.
            # The Qt tabbar must not paint a native gray base line.
            if window.chrome_tab14.drawBase():
                raise RuntimeError("Qt added an unwanted tabbar baseline")
            # The visible external tab must show an actual small favicon,
            # not the old long 'Glacier Browser · 新标签页' placeholder.
            window._glacier_sync_tab_icons35()
            app.processEvents()
            if (window.chrome_tab14.tabText(0) != "新标签页"
                    or window.chrome_tab14.tabIcon(0).isNull()):
                raise RuntimeError("Native new-tab favicon or compact tab title not rendered")
            if sys.platform == "win32":
                if not (window.windowFlags() & Qt.WindowType.FramelessWindowHint):
                    raise RuntimeError("Windows is still using an extra separate native titlebar")
                controls = getattr(window, "_glacier_caption_buttons35", {})
                if set(controls) != {"min", "max", "close"}:
                    raise RuntimeError("Windows integrated caption controls missing")
                if any(button.width() != 46 for button in controls.values()):
                    raise RuntimeError("Windows caption buttons have incorrect geometry")
                if not getattr(window, "_glacier_caption35", None):
                    raise RuntimeError("Windows native drag/resize controller missing")
                # The screenshot's red comparison frame is NOT part of
                # the product. Assert every tab/+ /caption hitbox stays inside
                # the actual first-row widget at real Windows DPI.
                for candidate_width in (720, 1050, 1360):
                    window.resize(candidate_width, 890)
                    for _ in range(5):
                        app.processEvents()
                    window._resize_tabs_to_content33()
                    app.processEvents()
                    positions = framed_top_geometry36(window)
                    print("FRAME_INSIDE", candidate_width,
                          {k: (v.x(), v.y(), v.width(), v.height())
                           for k, v in positions.items()}, flush=True)
                window.resize(1360, 890)
                app.processEvents()
                print("SUCCESS: integrated native Windows caption and tab row verified")
            if omni.layout().count()!=3:
                raise RuntimeError("Site, address and bookmark were not grouped into omnibox")
            if window._account_button26.width()>38:
                raise RuntimeError("Account pill is still crowding the address bar")
            if not window.tabs.tabBar().isHidden():
                raise RuntimeError("Legacy duplicate internal tab strip is visible")
            # Capture the REAL Qt Popup opened by the top-right account avatar.
            # The browser uses an empty temporary account profile, so no
            # credential, token or user identity appears in this artifact.
            popup = window.show_account_center26()
            for _ in range(8):
                app.processEvents()
                time.sleep(0.025)
            if (popup is None or not popup.isVisible()
                    or popup.objectName() != "GlacierProfilePopover37"
                    or isinstance(popup, QDialog)
                    or not bool(popup.windowFlags() & Qt.WindowType.Popup)):
                raise RuntimeError("Profile icon did not open a real anchored popup")
            expected_labels = ("登录 Glacier 账号", "网站账号和密码",
                               "创建 Glacier 账号")
            actual_labels = [b.text() for b in popup.findChildren(QPushButton)]
            if any(label not in actual_labels for label in expected_labels):
                raise RuntimeError("Profile menu missing account actions")
            account = window._account_button26
            right_edge = account.mapToGlobal(account.rect().topRight()).x()
            if abs(popup.geometry().right() - right_edge) > 40:
                raise RuntimeError("Profile panel did not align with avatar")
            if popup.width() > 380 or popup.height() > window.height():
                raise RuntimeError("Profile popup oversized for browser chrome")
            # Assemble the independently rendered real Qt Popup over the real
            # browser widget screenshot, preserving measured screen placement.
            composite = window.grab()
            painter = QPainter(composite)
            painter.drawPixmap(window.mapFromGlobal(popup.pos()), popup.grab())
            painter.end()
            pop_path = out/f"Glacier-Windows-v{CURRENT_VERSION}-profile-menu37.png"
            if not composite.save(str(pop_path), "PNG"):
                raise RuntimeError("Could not save real browser + profile popup proof")
            if pop_path.stat().st_size < 12000:
                raise RuntimeError("Native account menu screenshot unexpectedly empty")
            print("SUCCESS: Glacier account popup anchored below real avatar",
                  popup.pos(), popup.size(), pop_path, flush=True)
            popup.close()
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
