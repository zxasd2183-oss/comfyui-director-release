"""Xiaomi Mi Push Mainland China optional sender for Jipite V0.6.

Official HTTPS regId endpoint (2026): POST
https://api.xmpush.xiaomi.com/v2/message/regid

The push is a NOTIFICATION ONLY: it never carries approval authority,
secrets, signed challenges, or GPU API credentials.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

URL = "https://api.xmpush.xiaomi.com/v2/message/regid"
PACKAGE = "cn.borealos.jipite"


def send_xiaomi(reg_id: str, request_id: str, action: str,
                app_secret: str, ttl_ms: int = 300000, transport=None) -> None:
    """Raise on failure. Notify worker safely retries with backoff."""
    if not isinstance(reg_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,256}", reg_id):
        raise ValueError("invalid Xiaomi registration ID")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", request_id):
        raise ValueError("invalid request")
    if action not in ("start", "stop"):
        raise ValueError("invalid action")
    if not isinstance(app_secret, str) or not 8 <= len(app_secret) <= 256:
        raise ValueError("invalid server secret")
    if not isinstance(ttl_ms, int) or ttl_ms <= 0:
        raise ValueError("expired request")
    # Limit stale notifications: the app must still fetch the pending request
    # over authenticated TLS, and the VPS will reject an expired request.
    ttl_ms = min(ttl_ms, 300000)
    title = "吉皮提 · RTX 5090 开机申请" if action == "start" else "吉皮提 · RTX 5090 关机申请"
    description = "请打开吉皮提审批器，核对操作并验证指纹"
    payload = json.dumps({"kind": "gpu-approval", "request_id": request_id,
                          "action": action}, separators=(",", ":"), ensure_ascii=True)
    fields = {
        "registration_id": reg_id,
        "restricted_package_name": PACKAGE,
        "title": title,
        "description": description,
        "payload": payload,
        "time_to_live": str(ttl_ms),
        "extra.notify_effect": "1",  # open installed app, not browser
        "extra.only_send_once": "1",
    }
    request = Request(URL, data=urlencode(fields).encode("utf-8"),
                      method="POST", headers={
                          "Authorization": "key=" + app_secret,
                          "Content-Type": "application/x-www-form-urlencoded",
                          "Accept": "application/json",
                      })
    opener = transport if transport is not None else urlopen
    with opener(request, timeout=8) as response:
        raw = response.read(4097)
    if len(raw) > 4096:
        raise ValueError("unexpected push response")
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get("result") != "ok" or result.get("code") != 0:
        raise RuntimeError("xiaomi_push_not_accepted")
