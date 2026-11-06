"""Glacier Windows v0.20.1: standard pointer/HTML5 drag diagnostics.

This module does not automate, identify or bypass CAPTCHA challenges.
It provides a self-contained ordinary drag test and a user-initiated escape
hatch for sites incompatible with Qt WebEngine. Web data stays in Qt's own
profile; the system browser has independent cookies and login state.
"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QMessageBox


def diagnostic_page21() -> str:
    """A standalone, offline HTML page to separate app input from site behavior."""
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Glacier · 鼠标拖动诊断</title>
<style>
*{box-sizing:border-box}
body{font:15px "Segoe UI","Microsoft YaHei UI",sans-serif;background:#f7fbfe;color:#244054;
     max-width:920px;margin:40px auto;padding:0 24px}
h1{font-size:26px}p{color:#536c80;line-height:1.8}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}
.card{background:#fff;border:1px solid #dbeaf3;border-radius:18px;padding:22px}
.stage{position:relative;width:100%;height:175px;background:#eef7fc;border-radius:12px;overflow:hidden;
       touch-action:none;user-select:none}
.move{position:absolute;left:12px;top:60px;width:72px;height:54px;border-radius:12px;
      background:#4e96bf;color:white;display:grid;place-items:center;cursor:grab;
      touch-action:none;user-select:none}
.target{position:absolute;right:12px;top:60px;width:95px;height:54px;border:2px dashed #31a681;
        background:#e7fff3;border-radius:12px;display:grid;place-items:center;color:#168064}
.native{display:flex;align-items:center;justify-content:space-between;height:175px;
        border-radius:12px;background:#eef7fc;padding:12px}
.native [draggable]{width:94px;height:58px;background:#4e96bf;color:white;border-radius:10px;
                   display:grid;place-items:center;cursor:grab}
#drop{width:116px;height:70px;border:2px dashed #31a681;background:#e7fff3;border-radius:11px;
      display:grid;place-items:center;color:#168064}
.result{font-weight:600;margin-top:17px;color:#55758b}
.result.ok{color:#17835d}
</style></head>
<body>
<h1>❄ Glacier · 鼠标拖动诊断</h1>
<p>这是浏览器内置的本地测试页，不连接网络，也不识别或操作任何网站的安全验证。
请分别按住蓝色方块的鼠标左键，拖到绿色目标区再松开。</p>
<div class="grid">
<section class="card">
<h2>测试 A · Pointer Events</h2>
<div class="stage" id="stage">
  <div id="pointerTarget" class="target">目标</div>
  <div id="handle" class="move">拖动我</div>
</div>
<div id="pointerResult" class="result" role="status">待测试</div>
</section>
<section class="card">
<h2>测试 B · HTML5 拖放</h2>
<div class="native">
  <div id="nativeSource" draggable="true">拖动我</div>
  <div id="drop">拖到这里</div>
</div>
<div id="nativeResult" class="result" role="status">待测试</div>
</section>
</div>
<p>如果 A、B 都能成功，而某个网站的验证仍无法拖动，更可能是该网站的交互脚本
与嵌入式 Chromium 的兼容性问题。可使用 Glacier 菜单中的“在系统浏览器打开当前页”完成验证。</p>
<script>
"use strict";
(() => {
 const el=id=>document.getElementById(id);
 const handle=el("handle"), stage=el("stage"), target=el("pointerTarget");
 const pointer=el("pointerResult"), native=el("nativeResult");
 let pressed=false,dx=0,dy=0;
 handle.addEventListener("pointerdown",e=>{
   if(e.button!==0)return;
   pressed=true;
   const r=handle.getBoundingClientRect();
   dx=e.clientX-r.left;dy=e.clientY-r.top;
   handle.setPointerCapture(e.pointerId);
   pointer.textContent="已按下左键；正在检测拖动";
   e.preventDefault();
 });
 handle.addEventListener("pointermove",e=>{
   if(!pressed)return;
   const area=stage.getBoundingClientRect();
   const x=Math.max(0,Math.min(area.width-handle.offsetWidth,e.clientX-area.left-dx));
   const y=Math.max(0,Math.min(area.height-handle.offsetHeight,e.clientY-area.top-dy));
   handle.style.left=x+"px";
   handle.style.top=y+"px";
   pointer.textContent="已收到 PointerMove";
 });
 handle.addEventListener("pointerup",e=>{
   if(!pressed)return;
   pressed=false;
   const a=handle.getBoundingClientRect(), b=target.getBoundingClientRect();
   const overlap=a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;
   pointer.textContent=overlap?"通过：Pointer 拖动成功":"已经收到松开事件；请拖进绿色目标区";
   pointer.classList.toggle("ok",overlap);
 });
 handle.addEventListener("pointercancel",()=>{
   pressed=false;pointer.textContent="拖动被取消（PointerCancel）";
 });
 const source=el("nativeSource"), drop=el("drop");
 source.addEventListener("dragstart",e=>{
   e.dataTransfer.setData("text/plain","glacier-local-test");
   e.dataTransfer.effectAllowed="move";
   native.textContent="已收到 HTML5 dragstart";
 });
 drop.addEventListener("dragover",e=>e.preventDefault());
 drop.addEventListener("drop",e=>{
   e.preventDefault();
   const valid=e.dataTransfer.getData("text/plain")==="glacier-local-test";
   native.textContent=valid?"通过：HTML5 拖放成功":"目标接收到无效数据";
   native.classList.toggle("ok",valid);
 });
})();
</script></body></html>"""


def allowed_external_url21(url) -> bool:
    """Only navigate explicitly requested, valid HTTP(S) page URLs."""
    if not isinstance(url, QUrl) or not url.isValid():
        return False
    if url.scheme().lower() not in ("http", "https"):
        return False
    if not url.host() or url.userInfo():
        return False
    return True


class GlacierInput21:
    @staticmethod
    def prepare_page_input21(view):
        """Leave native QtWebEngine mouse/drag handlers fully in control."""
        view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        view.setMouseTracking(True)
        view.setAcceptDrops(True)

    def open_drag_diagnostic21(self):
        """User-visible offline test, never a CAPTCHA automation tool."""
        page = self.new_tab()
        if page is None:
            return
        page.setHtml(diagnostic_page21(), QUrl("about:blank"))
        if hasattr(self, "statusBar"):
            self.statusBar().showMessage(
                "本地拖动测试：分别拖动蓝色方块到绿色框", 6500
            )

    def open_in_system_browser21(self):
        """Explicit user action; does not copy browser cookies or credentials."""
        view = self.current()
        url = view.url() if view is not None else QUrl()
        if not allowed_external_url21(url):
            QMessageBox.information(
                self, "Glacier", "当前页面不是可在系统浏览器打开的 HTTP(S) 网址。"
            )
            return False
        try:
            ok = bool(webbrowser.open(url.toString(QUrl.ComponentFormattingOption.FullyEncoded)))
        except Exception:
            ok = False
        if hasattr(self, "statusBar"):
            self.statusBar().showMessage(
                "已交给系统浏览器；两个浏览器的登录状态是独立的"
                if ok else "系统浏览器未能打开；可以复制网址后手动访问", 7000
            )
        return ok
