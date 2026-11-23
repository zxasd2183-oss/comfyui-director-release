"""Native-feeling desktop password-save flow for Qt WebEngine.

Recognize a USER-SUBMITTED login form in Qt's isolated ApplicationWorld, then
ASK before saving into the pre-existing OS-encrypted Glacier account vault.
The page never receives access to the native credential store, and the bridge
cannot initiate an upload. Saved entries reuse existing E2E account sync.
"""
from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import urlsplit

from PySide6.QtCore import QFile, QUrl, QObject, QIODevice, QTimer, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWidgets import QMessageBox

from glacier_accounts22 import clean_accounts22, page_site22
from glacier_password_manager38 import GlacierPasswordManager38


CAPTURE_SCRIPT = r"""
(function(){
  'use strict';
  if (window.top !== window || window.__glacierPasswordCapture38) return;
  window.__glacierPasswordCapture38 = true;
  if (location.protocol !== 'https:' || typeof qt === 'undefined' || !qt.webChannelTransport ||
      typeof QWebChannel !== 'function') return;
  new QWebChannel(qt.webChannelTransport, function(channel) {
    var bridge = channel.objects.glacierNativePasswords38;
    if (!bridge || typeof bridge.submitted !== 'function') return;
    var last = '', lastAt = 0;
    function visible(input) {
      return input && input instanceof HTMLInputElement &&
             input.isConnected && !input.disabled && !input.readOnly &&
             input.getClientRects().length > 0 &&
             input.type !== 'hidden' &&
             input.getAttribute('aria-hidden') !== 'true';
    }
    function inspect(form) {
      if (!form || form.tagName !== 'FORM' || location.protocol !== 'https:') return;
      var fields = Array.from(form.querySelectorAll('input')).filter(visible);
      var pw = fields.filter(el => el.type === 'password' &&
                  el.autocomplete !== 'new-password');
      if (pw.length !== 1) return; // password reset, registration or ambiguous
      var us = fields.filter(el =>
          el !== pw[0] && ['text', 'email', 'tel'].includes(el.type) &&
          (el.autocomplete === 'username' || el.autocomplete === 'email' ||
           /(^|[\s_-])(user(name)?|e-?mail|login|account)([\s_-]|$)/i.test(
             [el.name,el.id].join(' '))));
      if (us.length !== 1 || !us[0].value || !pw[0].value) return;
      if (us[0].value.length > 250 || pw[0].value.length > 2048) return;
      // Never copy credentials out of a page on an untrusted origin or to
      // arbitrary webpage JS. In the isolated world the native channel is
      // available only to this injected script.
      var data = JSON.stringify({
          origin: location.origin, username: us[0].value, password: pw[0].value
      });
      if (data.length > 4900) return;
      var now = Date.now();
      if (data === last && now - lastAt < 7000) return;
      last = data; lastAt = now;
      bridge.submitted(data);
    }
    document.addEventListener('submit', function(e) {
      if (e.isTrusted && e.target && e.target.tagName === 'FORM') inspect(e.target);
    }, true);
    // Some SPA forms send network requests on a trusted submit-button click instead
    // of firing a form submit event. Do not observe arbitrary keystrokes.
    document.addEventListener('click', function(e) {
      if (!e.isTrusted) return;
      var btn = e.target && e.target.closest &&
                e.target.closest('button[type="submit"], input[type="submit"]');
      if (btn && btn.form) inspect(btn.form);
    }, true);
  });
})();
"""


def validated_submission(raw, page_url, active_page_url):
    """Strict first-party HTTPS origin check; never persist raw page messages."""
    if not isinstance(raw, str) or len(raw) > 4900:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {"origin", "username", "password"}:
            return None
        origin = urlsplit(data["origin"])
        visible = urlsplit(page_url)
        document = urlsplit(active_page_url)
        if (origin.scheme != "https" or origin.username or origin.password
                or origin.port not in (None, 443) or origin.path or origin.query or origin.fragment
                or not origin.hostname or not all(
                   url.scheme == "https" and url.hostname == origin.hostname
                   and url.port in (None, 443) and url.username is None
                   and url.password is None for url in (visible, document))):
            return None
        site = page_site22(QUrl(page_url))
        if not site or site != page_site22(QUrl(active_page_url)) or origin.hostname != site:
            return None
        user, pw = data["username"], data["password"]
        if (not isinstance(user, str) or not isinstance(pw, str)
                or not user.strip() or len(user) > 250 or not pw or len(pw) > 2048):
            return None
        if any(ord(x) < 32 or ord(x) == 127 for x in user):
            return None
        return {"site": site, "username": user, "password": pw}
    except (ValueError, TypeError, KeyError):
        return None


def updated_password_cards(existing, scope, submission):
    """Update only exact site+username+space; keep other credentials unchanged."""
    if scope not in ("private", "work") or not isinstance(existing, list):
        raise ValueError("Invalid local password vault")
    clean_accounts22({"schema": 1, "accounts": existing})
    records = [dict(r) for r in existing]
    matching = [i for i,r in enumerate(records)
                if r.get("space","private") == scope and
                r["site"] == submission["site"] and
                r["username"] == submission["username"]]
    if len(matching)>1:
        raise ValueError("Ambiguous saved login identity")
    if matching:
        records[matching[0]]["password"] = submission["password"]
    else:
        label = submission["username"][:60]
        names = {r["name"].casefold() for r in records
                 if r["site"] == submission["site"]
                 and r.get("space","private") == scope}
        if label.casefold() in names:
            for n in range(2,102):
                suffix = " ("+str(n)+")"
                name = label[:60-len(suffix)] + suffix
                if name.casefold() not in names:
                    label = name
                    break
            else:
                raise ValueError("Too many website password identities")
        records.append({"space": scope, "site": submission["site"],
                        "name": label, "username": submission["username"],
                        "password": submission["password"], "code_api": ""})
    return clean_accounts22({"schema": 1, "accounts": records})


class _NativePasswordBridge38(QObject):
    def __init__(self, owner, view):
        super().__init__(view)
        self._owner, self._view = owner, view

    @Slot(str)
    def submitted(self, payload):
        # Never log payload (contains a website password).
        self._owner._submitted_login38(self._view, payload)


class GlacierPasswordCapture38(GlacierPasswordManager38):
    def prepare_password_capture38(self, view):
        """Attach a separate isolated-world channel to each actual web page."""
        if getattr(view, "_glacier_password_ready38", False):
            return
        qrc = QFile(":/qtwebchannel/qwebchannel.js")
        if not qrc.open(QIODevice.OpenModeFlag.ReadOnly):
            return  # Fail closed if Qt's isolated channel bootstrap is missing.
        try:
            js = bytes(qrc.readAll()).decode("utf-8")
        finally:
            qrc.close()
        page = view.page()
        channel = QWebChannel(page)
        bridge = _NativePasswordBridge38(self, view)
        channel.registerObject("glacierNativePasswords38", bridge)
        world = QWebEngineScript.ScriptWorldId.ApplicationWorld
        page.setWebChannel(channel, world)
        capture = QWebEngineScript()
        capture.setName("GlacierNativePasswordCapture38")
        capture.setWorldId(world)
        capture.setRunsOnSubFrames(False)
        capture.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        capture.setSourceCode(js + "\n" + CAPTURE_SCRIPT)
        page.scripts().insert(capture)
        view._glacier_password_bridge38 = bridge
        view._glacier_password_channel38 = channel
        view._glacier_password_ready38 = True

    def _submitted_login38(self, view, raw):
        """Only foreground, first-party, explicitly submitted password forms."""
        if (not hasattr(self, "_accounts_doc22")
                or getattr(self, "_accounts_readonly22", True)
                or view is not self.current()
                or view.page() is None):
            return
        try:
            parsed = validated_submission(raw, view.url().toString(),
                                          view.page().url().toString())
        except RuntimeError:
            return
        if parsed is None:
            return
        space = self._account_space22()
        existing = self._accounts_doc22["accounts"]
        if any(row["site"] == parsed["site"]
               and row["username"] == parsed["username"]
               and row.get("space","private") == space
               and row["password"] == parsed["password"] for row in existing):
            return
        # The event dispatch and dialog must not force the page to pause or
        # block form submission; Qt signals are delivered on the GUI loop.
        captured = dict(parsed)
        QTimer.singleShot(0, lambda: self._ask_save_submitted38(view, space, captured))

    def _ask_save_submitted38(self, view, space, candidate):
        try:
            if (view is not self.current()
                    or not hasattr(self, "_accounts_doc22")
                    or getattr(self, "_accounts_readonly22", True)
                    or page_site22(view.url()) != candidate["site"]
                    or self._account_space22() != space):
                return
        except RuntimeError:
            return
        site, username = candidate["site"], candidate["username"]
        existing = self._accounts_doc22["accounts"]
        was_saved = any(row["site"] == site and row["username"] == username
                        and row.get("space", "private") == space for row in existing)
        message = (site + "\n" + username
                   + "\n\n保存到" + ("工作空间" if space == "work" else "私人空间")
                   + "的本机加密密码库。启用账号同步后可在授权设备上使用。")
        yes = QMessageBox.question(
            self, "更新网站密码？" if was_saved else "保存此网站密码？",
            message, QMessageBox.StandardButton.Save | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Save)
        if yes != QMessageBox.StandardButton.Save:
            return
        # Navigation, workspace or saved-record changes during the prompt
        # must not cause a stale password write.
        try:
            if (view is not self.current()
                    or page_site22(view.url()) != site
                    or self._account_space22() != space
                    or getattr(self, "_accounts_readonly22", True)):
                return
        except RuntimeError:
            return
        previous = self._accounts_doc22
        try:
            updated = updated_password_cards(previous["accounts"], space, candidate)
            self._accounts_doc22 = updated
            self._save_accounts22() # OS-encrypted atomic replace; triggers opt-in E2E sync.
        except Exception:
            self._accounts_doc22 = previous
            QMessageBox.warning(self, "密码保存失败",
                                "加密密码库无法写入，原来的账号资料已保留。")
            return
        status = getattr(self, "statusBar", None)
        if callable(status):
            status().showMessage("已保存网站密码 · "+site, 6000)
