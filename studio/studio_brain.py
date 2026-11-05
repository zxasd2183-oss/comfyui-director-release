"""Director Studio private brain-link: authenticated local MCP -> project ledger.

Only signed requests from the separately sandboxed Director Hub may access this
endpoint. No remote URL, GPU calls, shell commands, cloud secrets, or approvals.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from production_core import (
    ProductionError, open_db, verify_chain, create_project, create_episode,
    create_shot, dashboard, episode_detail, _ident, _text, transaction, _audit,
)

from visual_library import list_visuals

BRAIN_PATH="/api/v1/brain"
READ_TOOLS=frozenset({"get_production_dashboard","get_production_episode"})
WRITE_TOOLS=frozenset({
    "create_production_project","create_production_episode",
    "add_production_shot","save_production_outline",
})
ALL_TOOLS=READ_TOOLS | WRITE_TOOLS
KEY_NAME="brain_link"
MAX_BODY=32768
MAX_OUTLINE=12000
MAX_CLOCK_SKEW=60
MAX_NONCES=4096
HEX64=re.compile(r"^[0-9a-f]{64}$")
HEX32=re.compile(r"^[0-9a-f]{32}$")


class BrainError(ValueError):
    def __init__(self,reason,status=400):
        self.reason,self.status=reason,status
        super().__init__(reason)


def systemd_secret(environ=None):
    env=environ if environ is not None else os.environ
    directory=env.get("CREDENTIALS_DIRECTORY")
    if not directory:
        return None
    path=Path(directory)/KEY_NAME
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>128:
            return None
        value=path.read_text(encoding="ascii").strip()
        return bytes.fromhex(value) if HEX64.fullmatch(value) else None
    except (OSError,UnicodeError,ValueError):
        return None


def signature(secret,method,path,timestamp,nonce,body):
    digest=hashlib.sha256(body).hexdigest()
    message="\n".join((method,path,str(timestamp),nonce,digest)).encode("ascii")
    return hmac.new(secret,message,hashlib.sha256).hexdigest()


class BrainAuthenticator:
    def __init__(self,secret,clock=time.time):
        self.secret=secret if isinstance(secret,bytes) and len(secret)==32 else None
        self.clock=clock
        self.nonces={}
        self.lock=threading.Lock()

    def check(self,headers,method,path,body,client_ip):
        if (self.secret is None or client_ip!="127.0.0.1" or
                method!="POST" or path not in (BRAIN_PATH,"/api/v1/brain/visual") or
                headers.get("Host")!="127.0.0.1:8900" or
                headers.get("X-Forwarded-Host") is not None or
                headers.get("X-Forwarded-Proto") is not None or
                headers.get("X-Director-Studio-Auth-Mode") is not None or
                headers.get("Cookie") is not None or
                headers.get("Origin") is not None):
            return False
        timestamp=headers.get("X-Director-Brain-Time","")
        nonce=headers.get("X-Director-Brain-Nonce","")
        mac=headers.get("X-Director-Brain-Signature","")
        if (not re.fullmatch(r"[0-9]{10,11}",timestamp) or
                not HEX32.fullmatch(nonce) or not HEX64.fullmatch(mac)):
            return False
        now=self.clock()
        stamp=int(timestamp)
        if abs(now-stamp)>MAX_CLOCK_SKEW:
            return False
        expected=signature(self.secret,method,path,timestamp,nonce,body)
        if not hmac.compare_digest(expected,mac):
            return False
        with self.lock:
            self.nonces={k:v for k,v in self.nonces.items() if v>now}
            if nonce in self.nonces or len(self.nonces)>=MAX_NONCES:
                return False
            self.nonces[nonce]=now+MAX_CLOCK_SKEW*2
        return True


def _exact(args,expected):
    if not isinstance(args,dict) or set(args)!=set(expected):
        raise BrainError("invalid_brain_arguments")


def _outline(db,project_id,episode_id):
    row=db.execute(
        "SELECT revision,outline_sha256,body,updated_at FROM episode_outlines "
        "WHERE project_id=? AND episode_id=?", (project_id,episode_id)).fetchone()
    if row is None:
        return {"revision":0,"body":"","status":"not_written"}
    return {"revision":row["revision"],"body":row["body"],
            "sha256":row["outline_sha256"],"status":"draft",
            "updated_at":row["updated_at"]}


def _save_outline(db,pid,eid,body,expected_revision):
    if (not isinstance(body,str) or not body.strip() or len(body)>MAX_OUTLINE or
            "\x00" in body or any(ord(ch)<32 and ch not in "\r\n\t" for ch in body)):
        raise BrainError("invalid_outline")
    if type(expected_revision) is not int or not 0<=expected_revision<=100:
        raise BrainError("invalid_revision")
    digest=hashlib.sha256(body.encode("utf-8")).hexdigest()
    with transaction(db):
        if not db.execute("SELECT 1 FROM episodes WHERE project_id=? AND episode_id=?",
                          (pid,eid)).fetchone():
            raise BrainError("episode_not_found",404)
        previous=db.execute(
            "SELECT revision FROM episode_outlines WHERE project_id=? AND episode_id=?",
            (pid,eid)).fetchone()
        current=previous["revision"] if previous else 0
        if current!=expected_revision:
            raise BrainError("stale_outline_revision",409)
        newrev=current+1
        now=int(time.time())
        db.execute(
            "INSERT INTO episode_outlines(project_id,episode_id,revision,outline_sha256,body,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,episode_id) DO UPDATE SET "
            "revision=excluded.revision,outline_sha256=excluded.outline_sha256,"
            "body=excluded.body,updated_at=excluded.updated_at",
            (pid,eid,newrev,digest,body,now))
        db.execute(
            "INSERT INTO episode_outline_history(project_id,episode_id,revision,outline_sha256,body,updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (pid,eid,newrev,digest,body,now))
        _audit(db,"studio_brain","episode.outline_draft_saved",pid+"/"+eid,
               {"revision":newrev,"sha256":digest,"status":"draft"})
    return {"ok":True,"project_id":pid,"episode_id":eid,
            "revision":newrev,"sha256":digest,"status":"draft","gpu_action":False}


def execute(db_path,tool,args):
    if tool not in ALL_TOOLS:
        raise BrainError("brain_tool_not_allowed",403)
    if not isinstance(args,dict):
        raise BrainError("invalid_brain_arguments")
    try:
        with closing(open_db(db_path)) as db:
            if tool=="get_production_dashboard":
                _exact(args,())
                return {"ok":True,**dashboard(db)}
            if tool=="get_production_episode":
                _exact(args,("project_id","episode_id"))
                pid,eid=_ident(args["project_id"]),_ident(args["episode_id"])
                visuals=list_visuals(db_path,pid,eid)
                return {**episode_detail(db,pid,eid),
                        "outline":_outline(db,pid,eid),
                        "visuals":visuals["visuals"],
                        "visual_count":len(visuals["visuals"]),
                        "visuals_truncated":visuals["truncated"]}
            if not verify_chain(db):
                raise BrainError("audit_integrity_failure",409)
            if tool=="create_production_project":
                _exact(args,("project_id","title"))
                pid,title=_ident(args["project_id"]),_text(args["title"])
                if db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]>=20:
                    raise BrainError("project_limit_reached",409)
                create_project(db,pid,title,actor="studio_brain")
                return {"ok":True,"project_id":pid,"gpu_action":False}
            if tool=="create_production_episode":
                _exact(args,("project_id","episode_id","title","ordinal"))
                pid,eid=_ident(args["project_id"]),_ident(args["episode_id"])
                if db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]>=100:
                    raise BrainError("episode_limit_reached",409)
                create_episode(db,pid,eid,args["title"],args["ordinal"],
                               actor="studio_brain")
                return {"ok":True,"project_id":pid,"episode_id":eid,"gpu_action":False}
            if tool=="add_production_shot":
                _exact(args,("project_id","episode_id","shot_id","ordinal","duration_ms"))
                pid,eid=_ident(args["project_id"]),_ident(args["episode_id"])
                if db.execute(
                    "SELECT COUNT(*) FROM production_shots "
                    "WHERE project_id=? AND episode_id=?", (pid,eid)).fetchone()[0]>=500:
                    raise BrainError("shot_limit_reached",409)
                create_shot(db,pid,eid,args["shot_id"],args["ordinal"],args["duration_ms"],
                            actor="studio_brain")
                return {"ok":True,"project_id":pid,"episode_id":eid,
                        "shot_id":args["shot_id"],"gpu_action":False}
            if tool=="save_production_outline":
                _exact(args,("project_id","episode_id","body","expected_revision"))
                pid,eid=_ident(args["project_id"]),_ident(args["episode_id"])
                return _save_outline(db,pid,eid,args["body"],args["expected_revision"])
        raise BrainError("brain_tool_not_allowed",403)
    except ProductionError as exc:
        raise BrainError(str(exc),400) from None
    except sqlite3.IntegrityError:
        raise BrainError("duplicate_or_invalid_parent",409) from None
    except sqlite3.Error:
        raise BrainError("studio_storage_unavailable",503) from None
