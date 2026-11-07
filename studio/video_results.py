"""Immutable owner-imported MP4 takes, resumable uploads and manual review.

No GPU power, dispatch or remote URL ingestion. Every accepted video is
version-locked to an existing Studio handoff and verified by local ffprobe.
Browser uploads require the Studio Microsoft owner session, CSRF and Origin.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import secrets
import sqlite3
import subprocess
import time
from contextlib import closing

from production_core import (_ident, _shot_ident, _audit, open_db,
                             transaction, verify_chain, ProductionError)
from production_workflows import get_video_handoff_package, WorkflowError

MAX_VIDEO_BYTES = 250_000_000
CHUNK_BYTES = 786432
SESSION_SECONDS = 24 * 3600
MAX_ACTIVE_PER_PROJECT = 12
DIGEST = re.compile(r"^[0-9a-f]{64}$")
TAKE = re.compile(r"^(TAKE|UP)_[0-9a-f]{32}$")
PROMPT_ID = re.compile(r"^[A-Za-z0-9_-]{0,100}$")


class VideoResultError(ValueError):
    def __init__(self, reason, status=400):
        self.reason, self.status = reason, status
        super().__init__(reason)


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS studio_video_uploads(
      upload_id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL, episode_id TEXT NOT NULL, shot_id TEXT NOT NULL,
      owner TEXT NOT NULL, plan_revision INTEGER NOT NULL,
      package_sha256 TEXT NOT NULL, file_sha256 TEXT NOT NULL,
      size_bytes INTEGER NOT NULL, received_bytes INTEGER NOT NULL DEFAULT 0,
      prompt_id TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
      FOREIGN KEY(project_id,episode_id,shot_id)
        REFERENCES production_shots(project_id,episode_id,shot_id)
    );
    CREATE TABLE IF NOT EXISTS studio_video_takes(
      take_id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL, episode_id TEXT NOT NULL, shot_id TEXT NOT NULL,
      plan_revision INTEGER NOT NULL, package_sha256 TEXT NOT NULL,
      sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
      width INTEGER NOT NULL, height INTEGER NOT NULL,
      fps REAL NOT NULL, duration_seconds REAL NOT NULL,
      codec TEXT NOT NULL, prompt_id TEXT NOT NULL,
      status TEXT NOT NULL, review_reason TEXT,
      reviewer TEXT, created_at INTEGER NOT NULL, reviewed_at INTEGER,
      FOREIGN KEY(project_id,episode_id,shot_id)
        REFERENCES production_shots(project_id,episode_id,shot_id)
    );
    CREATE INDEX IF NOT EXISTS idx_studio_video_takes_shot
      ON studio_video_takes(project_id,episode_id,shot_id,created_at);
    """)


def _exact(data, keys):
    if not isinstance(data,dict) or set(data)!=set(keys):
        raise VideoResultError("invalid_video_result_fields")


def _valid_id(value):
    if not isinstance(value,str) or not TAKE.fullmatch(value):
        raise VideoResultError("invalid_video_record_id")
    return value


def _digest(value):
    if not isinstance(value,str) or not DIGEST.fullmatch(value):
        raise VideoResultError("invalid_video_sha256")
    return value


def _owner(value):
    if not isinstance(value,str) or not 1<=len(value)<=160:
        raise VideoResultError("invalid_video_owner")
    return value


def _safe_root(db_path, *, create=False):
    base=Path(db_path).parent
    root=base/"video_takes"
    if root.is_symlink():
        raise VideoResultError("unsafe_video_storage",503)
    if create:
        root.mkdir(mode=0o700,exist_ok=True)
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise VideoResultError("unsafe_video_storage",503)
    return root


def _check_scope(db, project, episode, shot):
    try:
        pid,eid,sid=_ident(project),_ident(episode),_shot_ident(shot)
    except ProductionError:
        raise VideoResultError("invalid_video_scope") from None
    if db.execute("SELECT 1 FROM production_shots WHERE project_id=? "
                  "AND episode_id=? AND shot_id=?",
                  (pid,eid,sid)).fetchone() is None:
        raise VideoResultError("video_shot_not_found",404)
    return pid,eid,sid


def _handoff(db_path, pid, eid, sid, revision, package_sha):
    try:
        obj=get_video_handoff_package(db_path,pid,eid,sid)
    except WorkflowError as exc:
        raise VideoResultError(exc.reason,exc.status) from exc
    package=obj["package"]
    if (package["video_plan"]["revision"]!=revision or
        obj["package_sha256"]!=package_sha):
        raise VideoResultError("video_source_revision_changed",409)
    if package["video_plan"]["status"]!="in_review":
        raise VideoResultError("video_plan_not_in_review",409)
    if package["blockers"]!=["video_render_executor_not_connected"]:
        raise VideoResultError("video_upstream_not_approved",409)
    return package


def _file_digest(path):
    digest=hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda:source.read(1<<20),b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video(path):
    """ffprobe checks the *uploaded MP4*, not claimed CLI metadata.

    Missing ffprobe is a hard error, never a reason to trust file extension.
    """
    try:
        completed=subprocess.run(
            ["/usr/bin/ffprobe","-v","error","-show_entries",
             "format=format_name,duration:stream=codec_type,codec_name,width,height,avg_frame_rate",
             "-of","json",str(path)],
            capture_output=True,timeout=20,check=True)
        result=json.loads(completed.stdout)
        streams=[x for x in result.get("streams",[])
                 if x.get("codec_type")=="video"]
        if len(streams)!=1 or not isinstance(result.get("format"),dict):
            raise ValueError
        video=streams[0]
        fmt=result["format"]
        if "mp4" not in fmt.get("format_name","").split(",") and (
            "mov" not in fmt.get("format_name","").split(",")):
            raise ValueError
        fr=video["avg_frame_rate"].split("/")
        fps=float(fr[0])/float(fr[1]) if len(fr)==2 else float(fr[0])
        duration=float(fmt["duration"])
        width,height=int(video["width"]),int(video["height"])
        codec=video["codec_name"]
        if not (1<=fps<=120 and .1<=duration<=60 and 1<=width<=16384
                and 1<=height<=16384 and isinstance(codec,str)
                and 1<=len(codec)<=40):
            raise ValueError
        return {"fps":fps,"duration_seconds":duration,"width":width,
                "height":height,"codec":codec}
    except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired,
            ValueError,KeyError,IndexError,TypeError,ZeroDivisionError,
            json.JSONDecodeError):
        raise VideoResultError("video_ffprobe_validation_failed",422) from None


def begin_upload(db_path, data, actor):
    _exact(data,("project_id","episode_id","shot_id","plan_revision",
                 "package_sha256","file_sha256","size_bytes","prompt_id"))
    owner=_owner(actor)
    revision=data["plan_revision"]
    size=data["size_bytes"]
    prompt=data["prompt_id"]
    if type(revision)!=int or not 1<=revision<=100000:
        raise VideoResultError("invalid_video_revision")
    if type(size)!=int or not 128<=size<=MAX_VIDEO_BYTES:
        raise VideoResultError("invalid_video_size",413)
    if not isinstance(prompt,str) or not PROMPT_ID.fullmatch(prompt):
        raise VideoResultError("invalid_video_prompt_id")
    source=_digest(data["package_sha256"])
    digest=_digest(data["file_sha256"])
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        if not verify_chain(db):
            raise VideoResultError("audit_integrity_failure",409)
        pid,eid,sid=_check_scope(db,data["project_id"],
                                 data["episode_id"],data["shot_id"])
        _handoff(db_path,pid,eid,sid,revision,source)
        root=_safe_root(db_path,create=True)
        now=int(time.time())
        with transaction(db):
            # Idempotency for owner-approved batch returns: an interrupted
            # 31-shot delivery should not create duplicate takes or re-upload
            # large immutable files that already passed verification.
            existing=db.execute("SELECT take_id FROM studio_video_takes WHERE "
                "project_id=? AND episode_id=? AND shot_id=? AND "
                "plan_revision=? AND package_sha256=? AND sha256=? AND "
                "size_bytes=? AND prompt_id=? AND status IN "
                "('in_review','approved','rejected') LIMIT 1",
                (pid,eid,sid,revision,source,digest,size,prompt)).fetchone()
            if existing:
                take_id=existing["take_id"]
                path=root/(take_id+".mp4")
                if path.is_symlink() or not path.is_file() or (
                    path.stat().st_size!=size or _file_digest(path)!=digest):
                    raise VideoResultError("video_take_storage_mismatch",503)
                return {"ok":True,"already_imported":True,
                    "take_id":take_id,"received_bytes":size,
                    "size_bytes":size,"gpu_action":False}
            # An upload is only resumable for 24 hours. Reap abandoned byte
            # files on the next owner start to avoid unbounded disk growth.
            expired=db.execute("SELECT upload_id FROM studio_video_uploads "
                "WHERE expires_at<=?",(now,)).fetchall()
            for item in expired:
                stale=root/(item["upload_id"]+".part")
                stale.unlink(missing_ok=True)
            db.execute("DELETE FROM studio_video_uploads WHERE expires_at<=?",(now,))
            # Reuse the same signed-in owner's exact upload after an interrupted
            # connection, never create duplicate overlapping upload sessions.
            row=db.execute("SELECT * FROM studio_video_uploads WHERE "
                "project_id=? AND episode_id=? AND shot_id=? AND "
                "owner=? AND plan_revision=? AND package_sha256=? AND "
                "file_sha256=? AND size_bytes=? AND prompt_id=? AND expires_at>?",
                (pid,eid,sid,owner,revision,source,digest,size,prompt,now)).fetchone()
            if row:
                path=root/(row["upload_id"]+".part")
                if path.is_file() and not path.is_symlink():
                    return {"ok":True,"upload_id":row["upload_id"],
                        "received_bytes":row["received_bytes"],
                        "size_bytes":size,"resumed":True,"gpu_action":False}
                db.execute("DELETE FROM studio_video_uploads WHERE upload_id=?",
                           (row["upload_id"],))
            active=db.execute("SELECT COUNT(*) FROM studio_video_uploads "
                "WHERE project_id=? AND expires_at>?",(pid,now)).fetchone()[0]
            if active>=MAX_ACTIVE_PER_PROJECT:
                raise VideoResultError("too_many_active_video_uploads",409)
            if shutil.disk_usage(root).free<size+100_000_000:
                raise VideoResultError("video_storage_space_insufficient",507)
            upload_id="UP_"+secrets.token_hex(16)
            target=root/(upload_id+".part")
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            os.close(fd)
            try:
                db.execute("INSERT INTO studio_video_uploads("
                    "upload_id,project_id,episode_id,shot_id,owner,plan_revision,"
                    "package_sha256,file_sha256,size_bytes,prompt_id,"
                    "created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (upload_id,pid,eid,sid,owner,revision,source,digest,size,
                     prompt,now,now+SESSION_SECONDS))
            except BaseException:
                target.unlink(missing_ok=True)
                raise
    return {"ok":True,"upload_id":upload_id,"received_bytes":0,
            "size_bytes":size,"resumed":False,"gpu_action":False}


def append_chunk(db_path,data,actor,lock):
    _exact(data,("upload_id","offset","chunk_base64"))
    uid=_valid_id(data["upload_id"])
    owner=_owner(actor)
    offset=data["offset"]
    if type(offset)!=int or offset<0:
        raise VideoResultError("invalid_video_chunk_offset")
    encoded=data["chunk_base64"]
    if not isinstance(encoded,str) or len(encoded)>CHUNK_BYTES*4//3+16:
        raise VideoResultError("invalid_video_chunk_size",413)
    try:
        chunk=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error):
        raise VideoResultError("invalid_video_chunk_payload") from None
    if not 1<=len(chunk)<=CHUNK_BYTES:
        raise VideoResultError("invalid_video_chunk_size",413)
    with lock:
        with closing(open_db(db_path)) as db:
            if not verify_chain(db):
                raise VideoResultError("audit_integrity_failure",409)
            with transaction(db):
                row=db.execute("SELECT * FROM studio_video_uploads WHERE "
                    "upload_id=? AND owner=?",(uid,owner)).fetchone()
                if row is None:raise VideoResultError("video_upload_not_found",404)
                if row["expires_at"]<=int(time.time()):
                    raise VideoResultError("video_upload_expired",409)
                current=row["received_bytes"]
                if offset!=current:
                    raise VideoResultError("video_upload_offset_conflict",409)
                if current+len(chunk)>row["size_bytes"]:
                    raise VideoResultError("video_chunk_exceeds_declared_size",413)
                root=_safe_root(db_path)
                target=root/(uid+".part")
                if target.is_symlink() or not target.is_file():
                    raise VideoResultError("video_upload_file_missing",409)
                fd=os.open(target,os.O_RDWR|os.O_NOFOLLOW)
                try:
                    with os.fdopen(fd,"r+b") as stream:
                        fd=None
                        stream.seek(0,os.SEEK_END)
                        actual=stream.tell()
                        if actual<current:
                            raise VideoResultError("video_upload_file_truncated",409)
                        if actual>current:
                            # Previous DB commit failed after bytes were written.
                            stream.truncate(current)
                        stream.write(chunk)
                        stream.flush()
                        os.fsync(stream.fileno())
                finally:
                    if fd is not None:os.close(fd)
                db.execute("UPDATE studio_video_uploads SET received_bytes=? "
                           "WHERE upload_id=?",(current+len(chunk),uid))
                return {"ok":True,"upload_id":uid,
                    "received_bytes":current+len(chunk),
                    "size_bytes":row["size_bytes"],"gpu_action":False}


def finish_upload(db_path,data,actor,lock):
    _exact(data,("upload_id",))
    uid=_valid_id(data["upload_id"])
    owner=_owner(actor)
    with lock:
        with closing(open_db(db_path)) as db:
            if not verify_chain(db):
                raise VideoResultError("audit_integrity_failure",409)
            row=db.execute("SELECT * FROM studio_video_uploads WHERE "
                "upload_id=? AND owner=?",(uid,owner)).fetchone()
            if row is None:raise VideoResultError("video_upload_not_found",404)
            if row["expires_at"]<=int(time.time()):
                raise VideoResultError("video_upload_expired",409)
            if row["received_bytes"]!=row["size_bytes"]:
                raise VideoResultError("video_upload_incomplete",409)
            pid,eid,sid=row["project_id"],row["episode_id"],row["shot_id"]
            package=_handoff(db_path,pid,eid,sid,row["plan_revision"],
                             row["package_sha256"])
            root=_safe_root(db_path)
            target=root/(uid+".part")
            if target.is_symlink() or not target.is_file():
                raise VideoResultError("video_upload_file_missing",409)
            if target.stat().st_size!=row["size_bytes"] or (
                _file_digest(target)!=row["file_sha256"]):
                raise VideoResultError("video_file_checksum_mismatch",422)
            with target.open("rb") as media:
                media.seek(4)
                if media.read(4)!=b"ftyp":
                    raise VideoResultError("not_mp4_file",422)
            details=probe_video(target)
            spec=package["upstream"]["settings"]["fields"]
            fps=float(spec["fps"])
            if (details["width"]!=int(float(spec["width"])) or
                details["height"]!=int(float(spec["height"])) or
                abs(details["fps"]-fps)>.1 or
                abs(details["duration_seconds"]-
                    package["duration_ms"]/1000)>max(.5,3/fps)):
                raise VideoResultError("video_does_not_match_approved_spec",422)
            take_id="TAKE_"+secrets.token_hex(16)
            final=root/(take_id+".mp4")
            target.rename(final)
            try:
                with transaction(db):
                    db.execute("INSERT INTO studio_video_takes("
                        "take_id,project_id,episode_id,shot_id,plan_revision,"
                        "package_sha256,sha256,size_bytes,width,height,fps,"
                        "duration_seconds,codec,prompt_id,status,created_at)"
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'in_review',?)",
                        (take_id,pid,eid,sid,row["plan_revision"],
                         row["package_sha256"],row["file_sha256"],
                         row["size_bytes"],details["width"],details["height"],
                         details["fps"],details["duration_seconds"],
                         details["codec"],row["prompt_id"],int(time.time())))
                    db.execute("DELETE FROM studio_video_uploads WHERE upload_id=?",
                               (uid,))
                    _audit(db,owner,"video.take_imported",take_id,{
                        "project_id":pid,"episode_id":eid,"shot_id":sid,
                        "plan_revision":row["plan_revision"],
                        "package_sha256":row["package_sha256"],
                        "media_sha256":row["file_sha256"],
                        "size_bytes":row["size_bytes"],"status":"in_review"})
            except BaseException:
                final.rename(target)
                raise
            return {"ok":True,"take_id":take_id,"status":"in_review",
                "media_sha256":row["file_sha256"],
                "width":details["width"],"height":details["height"],
                "fps":details["fps"],"duration_seconds":details["duration_seconds"],
                "gpu_action":False}


def _public(row):
    return {k:row[k] for k in (
        "take_id","project_id","episode_id","shot_id","plan_revision",
        "package_sha256","sha256","size_bytes","width","height","fps",
        "duration_seconds","codec","prompt_id","status","review_reason",
        "reviewer","created_at","reviewed_at")}


def list_takes(db_path,project_id,episode_id,shot_id):
    with closing(open_db(db_path,initialize=False)) as db:
        pid,eid,sid=_check_scope(db,project_id,episode_id,shot_id)
        rows=db.execute("SELECT * FROM studio_video_takes WHERE "
            "project_id=? AND episode_id=? AND shot_id=? "
            "ORDER BY created_at DESC,take_id DESC LIMIT 80",
            (pid,eid,sid)).fetchall()
        return {"ok":True,"project_id":pid,"episode_id":eid,
                "shot_id":sid,"takes":[_public(x) for x in rows],
                "gpu_action":False}


def get_take_file(db_path,project_id,episode_id,shot_id,take_id):
    uid=_valid_id(take_id)
    if not uid.startswith("TAKE_"):
        raise VideoResultError("invalid_video_record_id")
    with closing(open_db(db_path,initialize=False)) as db:
        pid,eid,sid=_check_scope(db,project_id,episode_id,shot_id)
        row=db.execute("SELECT * FROM studio_video_takes WHERE "
            "project_id=? AND episode_id=? AND shot_id=? AND take_id=?",
            (pid,eid,sid,uid)).fetchone()
        if row is None:raise VideoResultError("video_take_not_found",404)
        root=_safe_root(db_path)
        path=root/(uid+".mp4")
        if path.is_symlink() or not path.is_file() or (
            path.stat().st_size!=row["size_bytes"]):
            raise VideoResultError("video_take_storage_mismatch",503)
        return path,row["size_bytes"]


def review_take(db_path,data,actor):
    _exact(data,("project_id","episode_id","shot_id","take_id",
                 "decision","rationale"))
    owner=_owner(actor)
    decision=data["decision"]
    reason=data["rationale"]
    if decision not in ("approve","reject") or not isinstance(reason,str) or (
        not 8<=len(reason.strip())<=600):
        raise VideoResultError("video_review_reason_required")
    uid=_valid_id(data["take_id"])
    if not uid.startswith("TAKE_"):
        raise VideoResultError("invalid_video_record_id")
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise VideoResultError("audit_integrity_failure",409)
        pid,eid,sid=_check_scope(db,data["project_id"],
                                 data["episode_id"],data["shot_id"])
        with transaction(db):
            row=db.execute("SELECT * FROM studio_video_takes WHERE "
                "project_id=? AND episode_id=? AND shot_id=? AND take_id=?",
                (pid,eid,sid,uid)).fetchone()
            if row is None:raise VideoResultError("video_take_not_found",404)
            if row["status"]!="in_review":
                raise VideoResultError("video_take_already_reviewed",409)
            # Never allow a previously generated clip to approve a newer plan.
            if decision=="approve":
                _handoff(db_path,pid,eid,sid,row["plan_revision"],
                         row["package_sha256"])
                root=_safe_root(db_path)
                path=root/(uid+".mp4")
                if path.is_symlink() or not path.is_file() or (
                    path.stat().st_size!=row["size_bytes"] or
                    _file_digest(path)!=row["sha256"]):
                    raise VideoResultError("video_take_storage_mismatch",503)
            now=int(time.time())
            state={"approve":"approved","reject":"rejected"}[decision]
            db.execute("UPDATE studio_video_takes SET status=?,review_reason=?,"
                "reviewer=?,reviewed_at=? WHERE take_id=?",
                (state,reason.strip(),owner,now,uid))
            _audit(db,owner,"video.take_"+decision,uid,{
                "project_id":pid,"episode_id":eid,"shot_id":sid,
                "plan_revision":row["plan_revision"],"sha256":row["sha256"],
                "status":state})
        return {"ok":True,"take_id":uid,"status":state,"gpu_action":False}
