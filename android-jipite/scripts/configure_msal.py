#!/usr/bin/env python3
"""Configure an Android APK's MSAL redirect from a stable signing cert.

Inputs are PUBLIC registration metadata (Client ID, SHA-1 Base64 signature)
from environment. No Microsoft token, login password, private key or
cloud-GPU credential is read by this helper.
"""
from __future__ import annotations

import base64
import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import quote

PROJECT = Path(__file__).resolve().parents[1]
PACKAGE = "cn.borealos.jipite"


def configure(client_id: str, signing_hash: str) -> str:
    client = str(uuid.UUID(client_id))
    if client == str(uuid.UUID(int=0)):
        raise ValueError("The placeholder Microsoft Client ID is not permitted")
    try:
        decoded = base64.b64decode(signing_hash, validate=True)
    except Exception as exc:
        raise ValueError("Invalid signing hash") from exc
    if len(decoded) != 20 or not re.fullmatch(r"[A-Za-z0-9+/]{27}=", signing_hash):
        raise ValueError("Microsoft Android SHA-1 signature hash must be Base64(20 bytes)")

    config_file = PROJECT / "app/src/main/res/raw/msal_config.json"
    config = json.loads(config_file.read_text(encoding="utf-8"))
    config["client_id"] = client
    config["redirect_uri"] = "msauth://" + PACKAGE + "/" + quote(signing_hash, safe="")
    config["broker_redirect_uri_registered"] = False
    config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest_file = PROJECT / "app/src/main/AndroidManifest.xml"
    xml = manifest_file.read_text(encoding="utf-8")
    xml, count = re.subn(
        r'android:path="/[^"]+"',
        lambda _: 'android:path="/' + signing_hash + '"',
        xml,
        count=1,
    )
    if count != 1:
        raise ValueError("Microsoft BrowserTabActivity path not found")
    manifest_file.write_text(xml, encoding="utf-8")
    return signing_hash


if __name__ == "__main__":
    configure(os.environ["JIPITE_MS_CLIENT_ID"], os.environ["SIGNATURE_HASH"])
    print("Configured Android MSAL client and signing-certificate redirect without secrets")
