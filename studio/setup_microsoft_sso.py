#!/usr/bin/env python3
"""Local root-only one-time owner-bound Microsoft Web credential provisioner.

Reuses EXACT existing Android Microsoft app registration and original enrolled
Microsoft 'sub' from a read-only snapshot of the mobile approval database.
The user types a separate Web confidential-client credential in a private VPS
terminal. It is never passed through ChatGPT, a GitHub action, a shell command
argument, or a log.
"""
from __future__ import annotations
import getpass
import json
import os
import re
import sqlite3
import stat
import sys
from pathlib import Path

CLIENT = Path("/etc/comfyui-director-mobile-clientid")
POWERDB = Path("/var/lib/comfyui-director-power/requests.db")
CONFIG_DIR = Path("/etc/director-studio")
CONFIG = CONFIG_DIR / "msweb.json"
UUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
SUB = re.compile(r"^[A-Za-z0-9_-]{8,256}$")


class SetupError(ValueError):
    pass


def owner_binding(client_file=CLIENT, power_db=POWERDB):
    if client_file.is_symlink() or not client_file.is_file() or client_file.stat().st_size > 64:
        raise SetupError("existing_jipite_client_registration_missing")
    client_id = client_file.read_text(encoding="ascii").strip()
    if not UUID.fullmatch(client_id):
        raise SetupError("existing_jipite_client_id_invalid")
    if power_db.is_symlink() or not power_db.is_file():
        raise SetupError("existing_mobile_enrollment_unavailable")
    # Open read-only, do not copy approval secrets or affect active requests.
    db = sqlite3.connect("file:" + power_db.as_posix() + "?mode=ro", uri=True, timeout=5)
    try:
        rows = db.execute("SELECT owner_sub FROM mobile_device LIMIT 2").fetchall()
    except sqlite3.Error:
        raise SetupError("mobile_owner_enrollment_missing") from None
    finally:
        db.close()
    if len(rows) != 1 or not isinstance(rows[0][0], str) or not SUB.fullmatch(rows[0][0]):
        raise SetupError("exactly_one_pre_enrolled_personal_owner_required")
    return client_id, rows[0][0]


def provision(*, client_file=CLIENT, power_db=POWERDB, destination=CONFIG,
              read_secret=None):
    if os.geteuid() != 0:
        raise SetupError("root_required")
    client_id, owner_sub = owner_binding(client_file,power_db)
    dest = Path(destination)
    if dest.is_symlink() or dest.exists():
        raise SetupError("identity_credentials_already_exist_refusing_overwrite")
    if read_secret is None:
        read_secret = lambda: getpass.getpass(
            "Microsoft Web Client Secret VALUE (hidden; not the Secret ID): ")
    secret=read_secret()
    if (not isinstance(secret,str) or not 12 <= len(secret) <= 2048
            or any(ord(ch)<33 or ord(ch)>126 for ch in secret)):
        raise SetupError("invalid_microsoft_web_secret")
    dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if dest.parent.is_symlink():
        raise SetupError("credential_directory_symlink_refused")
    if dest.parent.stat().st_uid != 0:
        raise SetupError("credential_directory_not_root_owned")
    payload=json.dumps({"client_id":client_id,"client_secret":secret,
                        "owner_sub":owner_sub},ensure_ascii=False,separators=(",",":"))
    fd=os.open(str(dest),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            out.write(payload+"\n")
        os.chmod(dest,stat.S_IRUSR|stat.S_IWUSR)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    # Do not print or return client ID, owner sub or secret.
    return {"ok":True,"owner_bound_from_jipite":True,
            "client_registration_reused":True,"credential_stored_root_only":True}


def main():
    try:
        result=provision()
        print(json.dumps(result))
        print("Microsoft credentials are root-only. Never paste secret or owner sub in chat.")
        return 0
    except (OSError,sqlite3.Error,UnicodeError,SetupError,ValueError) as exc:
        print("Studio Microsoft credential setup refused: "+str(exc),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
