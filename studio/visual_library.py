"""Private, additive owner-only visual reference library for Director Studio.

Media lives next to production.sqlite in a service-owned directory; no GPU, remote
fetch, public URL imports, or filesystem paths from HTTP inputs are supported.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
import secrets
import sqlite3
import stat
import time
from contextlib import closing
from pathlib import Path

from production_core import (ProductionError, _ident, _shot_ident, _audit, open_db,
                             transaction, verify_chain)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_POST_BYTES = 11 * 1024 * 1024
ALLOWED_KINDS = frozenset({"character", "scene", "storyboard", "prop"})
MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class VisualError(ValueError):
    def __init__(self, reason, status=400):
        self.reason = reason
        self.status = status
        super().__init__(reason)


def prepare_schema(db):
    db.executescript("""
      CREATE TABLE IF NOT EXISTS visual_media (
        visual_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        episode_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        filename TEXT NOT NULL,
        mime TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        UNIQUE(project_id,episode_id,kind,subject_id,version),
        FOREIGN KEY(project_id,episode_id)
          REFERENCES episodes(project_id,episode_id)
      );
      CREATE TABLE IF NOT EXISTS visual_import_sources (
        visual_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL, episode_id TEXT NOT NULL,
        kind TEXT NOT NULL, subject_id TEXT NOT NULL,
        provider TEXT NOT NULL, source_file_id TEXT NOT NULL,
        imported_at INTEGER NOT NULL,
        UNIQUE(project_id,episode_id,kind,subject_id,provider,source_file_id),
        FOREIGN KEY(visual_id) REFERENCES visual_media(visual_id)
      );
      CREATE TABLE IF NOT EXISTS visual_selections (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL,
        episode_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        visual_id TEXT NOT NULL,
        selected_at INTEGER NOT NULL,
        FOREIGN KEY(visual_id) REFERENCES visual_media(visual_id)
      );
    """)


def media_directory(db_path, *, create=False):
    parent = Path(db_path).parent
    root = parent / "visual_media"
    if root.is_symlink():
        raise VisualError("media_directory_not_safe", 503)
    if create and not root.exists():
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            pass
    if not root.is_dir() or root.is_symlink():
        raise VisualError("media_storage_unavailable", 503)
    if root.stat().st_mode & 0o077:
        raise VisualError("media_permissions_unsafe", 503)
    return root


def verify_image(raw):
    if len(raw) < 32 or len(raw) > MAX_IMAGE_BYTES:
        raise VisualError("invalid_image_size", 413)
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and raw[12:16] == b"IHDR":
        width = int.from_bytes(raw[16:20], "big")
        height = int.from_bytes(raw[20:24], "big")
        mime = "image/png"
    elif raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9"):
        width = height = 1
        mime = "image/jpeg"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" and (
        int.from_bytes(raw[4:8], "little") + 8 == len(raw)
    ):
        width = height = 1
        mime = "image/webp"
    else:
        raise VisualError("unsupported_image_format", 415)
    if not 1 <= width <= 12000 or not 1 <= height <= 12000 or width*height > 60000000:
        raise VisualError("image_dimensions_out_of_range", 413)
    return mime


def _validate_scope(db, project_id, episode_id):
    pid, eid = _ident(project_id), _ident(episode_id)
    if not db.execute(
        "SELECT 1 FROM episodes WHERE project_id=? AND episode_id=?", (pid,eid)
    ).fetchone():
        raise VisualError("episode_not_found", 404)
    return pid, eid


def _subject_for_kind(kind,subject_id):
    # Production shot IDs deliberately include numeric values such as "01".
    # Keep the stricter project-style identifiers for characters/scenes/props.
    try:
        return (_shot_ident(subject_id) if kind=="storyboard"
                else _ident(subject_id))
    except ProductionError:
        raise VisualError("invalid_subject_id") from None


def _clean_filename(name):
    if not isinstance(name, str) or not 1 <= len(name) <= 120:
        raise VisualError("invalid_filename")
    if any(c in name for c in ("/", "\\", "\x00")) or any(ord(c)<32 for c in name):
        raise VisualError("invalid_filename")
    return name


def list_visuals(db_path, project_id, episode_id):
    with closing(open_db(db_path, initialize=False)) as db:
        pid, eid = _validate_scope(db, project_id, episode_id)
        records = db.execute(
            "SELECT visual_id,kind,subject_id,version,filename,mime,size_bytes,"
            "sha256,created_at FROM visual_media "
            "WHERE project_id=? AND episode_id=? "
            "ORDER BY kind,subject_id,version DESC LIMIT 251", (pid,eid)
        ).fetchall()
        selections = db.execute(
            "SELECT kind,subject_id,visual_id FROM visual_selections "
            "WHERE project_id=? AND episode_id=? ORDER BY seq", (pid,eid)
        ).fetchall()
        selected = {(x["kind"],x["subject_id"]):x["visual_id"] for x in selections}
        imports={r["visual_id"] for r in db.execute(
            "SELECT visual_id FROM visual_import_sources WHERE project_id=? AND episode_id=?",
            (pid,eid)).fetchall()}
        return {"ok":True,"project_id":pid,"episode_id":eid,
                "visuals":[{**dict(row),
                            "selected":selected.get((row["kind"],row["subject_id"]))==row["visual_id"],
                            "source":"ChatGPT" if row["visual_id"] in imports else "Studio"}
                           for row in records[:250]],
                "truncated":len(records)>250}


def upload_visual(db_path, data, actor):
    fields = {"project_id","episode_id","kind","subject_id","filename","image_base64"}
    if not isinstance(data, dict) or set(data) != fields:
        raise VisualError("invalid_visual_fields")
    kind = data["kind"]
    if kind not in ALLOWED_KINDS:
        raise VisualError("invalid_visual_kind")
    subject=_subject_for_kind(kind,data["subject_id"])
    filename = _clean_filename(data["filename"])
    if not isinstance(data["image_base64"],str):
        raise VisualError("invalid_image_payload")
    try:
        raw = base64.b64decode(data["image_base64"],validate=True)
    except (ValueError,binascii.Error):
        raise VisualError("invalid_image_payload") from None
    mime = verify_image(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with closing(open_db(db_path,initialize=True)) as db:
        prepare_schema(db)
        if not verify_chain(db):
            raise VisualError("audit_integrity_failure",409)
        pid,eid = _validate_scope(db,data["project_id"],data["episode_id"])
        count=db.execute(
            "SELECT COUNT(*) FROM visual_media WHERE project_id=? AND episode_id=?",
            (pid,eid)).fetchone()[0]
        if count>=250:
            raise VisualError("episode_visual_limit_reached",409)
        root=media_directory(db_path,create=True)
        visual_id="VIS_"+secrets.token_hex(12)
        version=db.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM visual_media "
            "WHERE project_id=? AND episode_id=? AND kind=? AND subject_id=?",
            (pid,eid,kind,subject)).fetchone()[0]
        path=root/(visual_id+MIME_EXT[mime])
        fd=None
        try:
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,"wb") as f:
                fd=None
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            with transaction(db):
                db.execute(
                    "INSERT INTO visual_media "
                    "(visual_id,project_id,episode_id,kind,subject_id,version,"
                    "filename,mime,size_bytes,sha256,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (visual_id,pid,eid,kind,subject,version,filename,mime,
                     len(raw),digest,int(time.time())))
                _audit(db,actor,"visual.uploaded",visual_id,
                       {"project_id":pid,"episode_id":eid,"kind":kind,
                        "subject_id":subject,"version":version,"sha256":digest})
        except BaseException:
            if fd is not None:
                os.close(fd)
            path.unlink(missing_ok=True)
            raise
    return {"ok":True,"visual_id":visual_id,"version":version,
            "kind":kind,"subject_id":subject,"gpu_action":False}


def ingest_chatgpt_image(db_path, data, actor="chatgpt_sync"):
    """Atomically register image bytes, source provenance and audit history.

    All DB writes use one BEGIN IMMEDIATE transaction, so concurrent retry of
    the same file cannot create duplicate versions. If the DB commit fails,
    the newly written file is removed and no half-synced asset is published.
    """
    fields={"project_id","episode_id","kind","subject_id","filename",
            "source_file_id","image_base64"}
    if not isinstance(data,dict) or set(data)!=fields:
        raise VisualError("invalid_visual_fields")
    source=data["source_file_id"]
    import re
    if (not isinstance(source,str) or
            not re.fullmatch(r"file[_-][A-Za-z0-9_-]{5,180}",source)):
        raise VisualError("invalid_source_file_id")
    kind=data["kind"]
    if kind not in ALLOWED_KINDS:
        raise VisualError("invalid_visual_kind")
    subject=_subject_for_kind(kind,data["subject_id"])
    filename=_clean_filename(data["filename"])
    encoded=data["image_base64"]
    if not isinstance(encoded,str):
        raise VisualError("invalid_image_payload")
    try:
        raw=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error):
        raise VisualError("invalid_image_payload") from None
    mime=verify_image(raw)
    digest=hashlib.sha256(raw).hexdigest()

    with closing(open_db(db_path,initialize=True)) as db:
        prepare_schema(db)
        if not verify_chain(db):
            raise VisualError("audit_integrity_failure",409)
        pid,eid=_validate_scope(db,data["project_id"],data["episode_id"])
        path=None
        file_created=False
        try:
            with transaction(db):
                existing=db.execute(
                    "SELECT m.visual_id,m.version,m.sha256 FROM visual_import_sources s "
                    "JOIN visual_media m ON m.visual_id=s.visual_id "
                    "WHERE s.project_id=? AND s.episode_id=? AND s.kind=? "
                    "AND s.subject_id=? AND s.provider='chatgpt' AND s.source_file_id=?",
                    (pid,eid,kind,subject,source)).fetchone()
                if existing:
                    if existing["sha256"]!=digest:
                        raise VisualError("source_file_integrity_conflict",409)
                    return {"ok":True,"visual_id":existing["visual_id"],
                            "version":existing["version"],"unchanged":True,
                            "gpu_action":False}
                # ChatGPT can issue a different opaque file ID on every tool call.
                # Scope deduplication to EXACT image bytes + episode + type +
                # subject, not the ephemeral source ID. Reuse the OLDEST
                # version if pre-fix runs already created duplicate candidates.
                same_bytes=db.execute(
                    "SELECT visual_id,version FROM visual_media "
                    "WHERE project_id=? AND episode_id=? AND kind=? "
                    "AND subject_id=? AND sha256=? AND size_bytes=? "
                    "ORDER BY version ASC LIMIT 1",
                    (pid,eid,kind,subject,digest,len(raw))).fetchone()
                if same_bytes:
                    return {"ok":True,"visual_id":same_bytes["visual_id"],
                            "version":same_bytes["version"],"unchanged":True,
                            "gpu_action":False}
                count=db.execute(
                    "SELECT COUNT(*) FROM visual_media WHERE project_id=? AND episode_id=?",
                    (pid,eid)).fetchone()[0]
                if count>=250:
                    raise VisualError("episode_visual_limit_reached",409)
                version=db.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM visual_media "
                    "WHERE project_id=? AND episode_id=? AND kind=? AND subject_id=?",
                    (pid,eid,kind,subject)).fetchone()[0]
                root=media_directory(db_path,create=True)
                visual_id="VIS_"+secrets.token_hex(12)
                path=root/(visual_id+MIME_EXT[mime])
                fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
                file_created=True
                with os.fdopen(fd,"wb") as f:
                    f.write(raw)
                    f.flush()
                    os.fsync(f.fileno())
                now=int(time.time())
                db.execute(
                    "INSERT INTO visual_media "
                    "(visual_id,project_id,episode_id,kind,subject_id,version,"
                    "filename,mime,size_bytes,sha256,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (visual_id,pid,eid,kind,subject,version,filename,mime,
                     len(raw),digest,now))
                db.execute(
                    "INSERT INTO visual_import_sources "
                    "(visual_id,project_id,episode_id,kind,subject_id,provider,"
                    "source_file_id,imported_at) VALUES(?,?,?,?,?,?,?,?)",
                    (visual_id,pid,eid,kind,subject,"chatgpt",source,now))
                _audit(db,actor,"visual.uploaded",visual_id,
                       {"project_id":pid,"episode_id":eid,"kind":kind,
                        "subject_id":subject,"version":version,"sha256":digest})
                _audit(db,actor,"visual.source_linked",visual_id,
                       {"provider":"chatgpt","project_id":pid,"episode_id":eid,
                        "kind":kind,"subject_id":subject})
            return {"ok":True,"visual_id":visual_id,"version":version,
                    "kind":kind,"subject_id":subject,
                    "unchanged":False,"gpu_action":False}
        except BaseException:
            if file_created and path is not None:
                path.unlink(missing_ok=True)
            raise


def select_visual(db_path, data, actor):
    if not isinstance(data,dict) or set(data)!={"project_id","episode_id","visual_id"}:
        raise VisualError("invalid_visual_fields")
    with closing(open_db(db_path,initialize=True)) as db:
        prepare_schema(db)
        if not verify_chain(db):
            raise VisualError("audit_integrity_failure",409)
        pid,eid=_validate_scope(db,data["project_id"],data["episode_id"])
        visual_id=_ident(data["visual_id"])
        row=db.execute(
            "SELECT kind,subject_id FROM visual_media "
            "WHERE project_id=? AND episode_id=? AND visual_id=?",
            (pid,eid,visual_id)).fetchone()
        if not row:
            raise VisualError("visual_not_found",404)
        # Only append a selection event; never rewrite candidates or old choices.
        with transaction(db):
            db.execute(
                "INSERT INTO visual_selections "
                "(project_id,episode_id,kind,subject_id,visual_id,selected_at) "
                "VALUES(?,?,?,?,?,?)",
                (pid,eid,row["kind"],row["subject_id"],visual_id,int(time.time())))
            _audit(db,actor,"visual.selected",visual_id,
                   {"project_id":pid,"episode_id":eid,"kind":row["kind"],
                    "subject_id":row["subject_id"]})
        return {"ok":True,"visual_id":visual_id,"selected":True,"gpu_action":False}


def read_visual(db_path, project_id, episode_id, visual_id):
    visual_id=_ident(visual_id)
    with closing(open_db(db_path,initialize=False)) as db:
        pid,eid=_validate_scope(db,project_id,episode_id)
        row=db.execute(
            "SELECT mime,sha256,size_bytes FROM visual_media "
            "WHERE project_id=? AND episode_id=? AND visual_id=?",
            (pid,eid,visual_id)).fetchone()
        if row is None:
            raise VisualError("visual_not_found",404)
    root=media_directory(db_path)
    path=root/(visual_id+MIME_EXT[row["mime"]])
    if path.is_symlink():
        raise VisualError("media_file_not_safe",503)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,"rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise VisualError("media_file_not_safe",503)
        raw=f.read(MAX_IMAGE_BYTES+1)
    if (len(raw)!=row["size_bytes"] or
        hashlib.sha256(raw).hexdigest()!=row["sha256"]):
        raise VisualError("media_integrity_failure",503)
    return row["mime"],raw
