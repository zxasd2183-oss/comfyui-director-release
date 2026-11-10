"""macOS connectivity mixin: same UI as GlacierUI08, explicit bundled TLS CA."""
from __future__ import annotations
import threading
import time
from ui08 import GlacierUI08
from mac_https_probe import check_via_socks
from mac_proxy_diagnostics import latest_hint


class MacGlacierUI08(GlacierUI08):
    def start_connection_check(self):
        if self.check_busy:
            return
        if not self.proc or self.proc.poll() is not None:
            self._poll_proxy()
            return
        self.check_busy=True
        self.test_btn.setEnabled(False)
        self.proxy_status.setText("● 正在通过 VLESS 验证 HTTPS 证书…")

        def worker():
            try:
                ok,message=check_via_socks(self.proxy_port)
            except Exception as exc:
                # Give sing-box's stderr reader a brief chance to receive the
                # underlying outbound handshake error after SOCKS5 code 1.
                time.sleep(0.12)
                hint=latest_hint(self.proc)
                message="HTTPS 检测失败："+str(exc)[:140]
                if hint:
                    message+="；内核诊断："+hint
                ok=False
            self.check_signals.checked.emit(ok,message)

        threading.Thread(target=worker,name="glacier-macos-tls-check",daemon=True).start()
