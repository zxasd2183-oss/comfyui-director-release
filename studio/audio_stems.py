"""Episode-length WAV stem intake, immutable provenance and manual sound review.

Independent of GPU and generated speech. Three explicit 48kHz stereo PCM
stems: dialogue, music and effects. Their presence, rights evidence, sound
quality and approval are separate from the picture cut approval.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing

from production_core import open_db, transaction, _audit, verify_chain, _ident, ProductionError
from video_results import CHUNK_BYTES, _file_digest

MAX_BYTES=150_000_000
DIGEST=re.compile(r"^[a-f0-9]{64}$")
ID=re.compile(r"^(?:AUP|AUD)_[a-f0-9]{32}$")
STEMS=frozenset(("dialogue","music","effects"))
SESSION_SECONDS=24*3600
MAX_ACTIVE=12


class AudioError(ValueError):
    def __init__(self,reason,status=400):
        self.reason,self.status=reason,status
        super().__init__(reason)


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS studio_audio_uploads(
        upload_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,episode_id TEXT NOT NULL,stem TEXT NOT NULL,
        owner TEXT NOT NULL,rights_ref TEXT NOT NULL,
        file_sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,
        received_bytes INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
        FOREIGN KEY(project_id,episode_id) REFERENCES episodes(project_id,episode_id)
    );
    CREATE TABLE IF NOT EXISTS studio_audio_stems(
        audio_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,episode_id TEXT NOT NULL,stem TEXT NOT NULL,
        revision INTEGER NOT NULL,
        rights_ref TEXT NOT NULL,
        sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,
        duration_seconds REAL NOT NULL,sample_rate INTEGER NOT NULL,
        channels INTEGER NOT NULL,codec TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('in_review','approved','rejected')),
        reviewer TEXT,review_reason TEXT,
        created_at INTEGER NOT NULL,reviewed_at INTEGER,
        UNIQUE(project_id,episode_id,stem,revision),
        FOREIGN KEY(project_id,episode_id) REFERENCES episodes(project_id,episode_id)
    );
    CREATE INDEX IF NOT EXISTS idx_audio_stem_episode
        ON studio_audio_stems(project_id,episode_id,stem,created_at);
    """)


def _scope(db,project,episode):
    try:pid,eid=_ident(project),_ident(episode)
    except ProductionError:raise AudioError("invalid_audio_scope") from None
    if db.execute("SELECT 1 FROM episodes WHERE project_id=? "
                  "AND episode_id=?",(pid,eid)).fetchone() is None:
        raise AudioError("audio_episode_not_found",404)
    return pid,eid


def _root(db_path,create=False):
    root=Path(db_path).parent/"audio_stems"
    if root.is_symlink():
        raise AudioError("unsafe_audio_storage",503)
    if create:root.mkdir(mode=0o700,exist_ok=True)
    if not root.is_dir() or root.stat().st_mode&0o077:
        raise AudioError("unsafe_audio_storage",503)
    return root


def _uid(value,prefix):
    if not isinstance(value,str) or not ID.fullmatch(value) or not value.startswith(prefix):
        raise AudioError("invalid_audio_record_id")
    return value


def _stem(value):
    if value not in STEMS or not isinstance(value,str):
        raise AudioError("invalid_audio_stem")
    return value


def _actor(value):
    if not isinstance(value,str) or not 1<=len(value)<=160:
        raise AudioError("invalid_audio_actor")
    return value


def _digest(value):
    if not isinstance(value,str) or not DIGEST.fullmatch(value):
        raise AudioError("invalid_audio_sha256")
    return value


def _rights(value):
    if not isinstance(value,str) or not 8<=len(value.strip())<=500 or (
        any(ord(c)<32 for c in value)):
        raise AudioError("audio_rights_evidence_required")
    return value.strip()


def _fields(data,required):
    if not isinstance(data,dict) or set(data)!=set(required):
        raise AudioError("invalid_audio_fields")


def _duration(db,pid,eid):
    rows=db.execute("SELECT duration_ms FROM production_shots "
        "WHERE project_id=? AND episode_id=?",(pid,eid)).fetchall()
    if not rows or len(rows)>500:raise AudioError("audio_episode_shots_missing",409)
    return sum(x["duration_ms"] for x in rows)/1000


def probe_wav(file):
    try:
        process=subprocess.run(["/usr/bin/ffprobe","-v","error",
            "-show_entries","format=format_name,duration:"
                "stream=codec_type,codec_name,sample_rate,channels",
            "-of","json",str(file)],capture_output=True,check=True,timeout=25)
        if len(process.stdout)>64000:raise ValueError
        report=json.loads(process.stdout)
        tracks=report["streams"]
        if len(tracks)!=1 or tracks[0].get("codec_type")!="audio" or (
            report["format"]["format_name"]!="wav"):
            raise ValueError
        track=tracks[0]
        codec=track["codec_name"]
        rate=int(track["sample_rate"])
        channels=int(track["channels"])
        duration=float(report["format"]["duration"])
        if codec not in ("pcm_s16le","pcm_s24le") or rate!=48000 or (
            channels!=2) or not .1<=duration<=3600:
            raise ValueError
        return {"codec":codec,"sample_rate":rate,"channels":channels,
                "duration_seconds":duration}
    except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired,
            json.JSONDecodeError,TypeError,ValueError,KeyError,IndexError):
        raise AudioError("audio_wav_format_invalid",422) from None


def start(db_path,data,actor):
    _fields(data,("project_id","episode_id","stem","file_sha256",
                  "size_bytes","rights_ref"))
    who=_actor(actor)
    stem=_stem(data["stem"])
    digest=_digest(data["file_sha256"])
    rights=_rights(data["rights_ref"])
    size=data["size_bytes"]
    if type(size)!=int or not 128<=size<=MAX_BYTES:
        raise AudioError("audio_file_size_invalid",413)
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        if not verify_chain(db):
            raise AudioError("audit_integrity_failure",409)
        pid,eid=_scope(db,data["project_id"],data["episode_id"])
        _duration(db,pid,eid)
        root=_root(db_path,create=True)
        now=int(time.time())
        with transaction(db):
            # Exact immutable audio may already be present after a retry;
            # do not turn it into an extra unreviewed revision.
            existing=db.execute("SELECT audio_id,status FROM studio_audio_stems "
                "WHERE project_id=? AND episode_id=? AND stem=? AND "
                "sha256=? AND size_bytes=? AND rights_ref=? "
                "ORDER BY revision DESC LIMIT 1",
                (pid,eid,stem,digest,size,rights)).fetchone()
            if existing:
                path=root/(existing["audio_id"]+".wav")
                if path.is_symlink() or not path.is_file() or (
                    path.stat().st_size!=size or _file_digest(path)!=digest):
                    raise AudioError("audio_storage_mismatch",503)
                return {"ok":True,"already_imported":True,
                    "audio_id":existing["audio_id"],"status":existing["status"],
                    "received_bytes":size,"size_bytes":size,"gpu_action":False}
            expired=db.execute("SELECT upload_id FROM studio_audio_uploads "
                "WHERE expires_at<=?",(now,)).fetchall()
            for item in expired:
                (root/(item["upload_id"]+".part")).unlink(missing_ok=True)
            db.execute("DELETE FROM studio_audio_uploads WHERE expires_at<=?",(now,))
            resumed=db.execute("SELECT upload_id,received_bytes FROM studio_audio_uploads "
                "WHERE project_id=? AND episode_id=? AND stem=? AND owner=? AND "
                "rights_ref=? AND file_sha256=? AND size_bytes=? AND expires_at>? "
                "ORDER BY created_at DESC LIMIT 1",
                (pid,eid,stem,who,rights,digest,size,now)).fetchone()
            if resumed:
                path=root/(resumed["upload_id"]+".part")
                if path.is_file() and not path.is_symlink():
                    return {"ok":True,"upload_id":resumed["upload_id"],
                        "received_bytes":resumed["received_bytes"],
                        "size_bytes":size,"resumed":True,"gpu_action":False}
                db.execute("DELETE FROM studio_audio_uploads WHERE upload_id=?",
                           (resumed["upload_id"],))
            active=db.execute("SELECT COUNT(*) FROM studio_audio_uploads "
                "WHERE project_id=? AND expires_at>?",(pid,now)).fetchone()[0]
            if active>=MAX_ACTIVE:
                raise AudioError("audio_upload_limit_reached",409)
            if shutil.disk_usage(root).free<size+100_000_000:
                raise AudioError("audio_storage_space_insufficient",507)
            uid="AUP_"+secrets.token_hex(16)
            path=root/(uid+".part")
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            os.close(fd)
            try:
                db.execute("INSERT INTO studio_audio_uploads("
                    "upload_id,project_id,episode_id,stem,owner,rights_ref,"
                    "file_sha256,size_bytes,created_at,expires_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (uid,pid,eid,stem,who,rights,digest,size,now,now+SESSION_SECONDS))
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            return {"ok":True,"upload_id":uid,"received_bytes":0,
                    "size_bytes":size,"resumed":False,"gpu_action":False}


def append(db_path,data,actor,lock):
    _fields(data,("upload_id","offset","chunk_base64"))
    uid=_uid(data["upload_id"],"AUP_")
    who=_actor(actor)
    offset=data["offset"]
    text=data["chunk_base64"]
    if type(offset)!=int or offset<0 or not isinstance(text,str) or (
        len(text)>CHUNK_BYTES*4//3+16):
        raise AudioError("invalid_audio_chunk",413)
    try:chunk=base64.b64decode(text,validate=True)
    except (ValueError,binascii.Error):
        raise AudioError("invalid_audio_chunk") from None
    if not 1<=len(chunk)<=CHUNK_BYTES:
        raise AudioError("invalid_audio_chunk",413)
    with lock:
        with closing(open_db(db_path)) as db:
            if not verify_chain(db):
                raise AudioError("audit_integrity_failure",409)
            with transaction(db):
                row=db.execute("SELECT * FROM studio_audio_uploads WHERE "
                    "upload_id=? AND owner=?",(uid,who)).fetchone()
                if row is None:raise AudioError("audio_upload_not_found",404)
                if row["expires_at"]<=int(time.time()):
                    raise AudioError("audio_upload_expired",409)
                current=row["received_bytes"]
                if offset!=current:
                    raise AudioError("audio_upload_offset_conflict",409)
                if current+len(chunk)>row["size_bytes"]:
                    raise AudioError("audio_chunk_too_large",413)
                path=_root(db_path)/(uid+".part")
                if path.is_symlink() or not path.is_file():
                    raise AudioError("audio_upload_storage_missing",409)
                fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW)
                try:
                    with os.fdopen(fd,"r+b") as target:
                        fd=None
                        target.seek(0,os.SEEK_END)
                        current_size=target.tell()
                        if current_size<current:
                            raise AudioError("audio_upload_truncated",409)
                        if current_size>current:
                            target.truncate(current)
                        target.write(chunk)
                        target.flush()
                        os.fsync(target.fileno())
                finally:
                    if fd is not None:os.close(fd)
                db.execute("UPDATE studio_audio_uploads SET received_bytes=? "
                    "WHERE upload_id=?",(current+len(chunk),uid))
                return {"ok":True,"upload_id":uid,
                    "received_bytes":current+len(chunk),
                    "size_bytes":row["size_bytes"],"gpu_action":False}


def finish(db_path,data,actor,lock):
    _fields(data,("upload_id",))
    uid=_uid(data["upload_id"],"AUP_")
    who=_actor(actor)
    with lock:
        with closing(open_db(db_path)) as db:
            if not verify_chain(db):
                raise AudioError("audit_integrity_failure",409)
            row=db.execute("SELECT * FROM studio_audio_uploads WHERE "
                "upload_id=? AND owner=?",(uid,who)).fetchone()
            if row is None:raise AudioError("audio_upload_not_found",404)
            if row["received_bytes"]!=row["size_bytes"]:
                raise AudioError("audio_upload_incomplete",409)
            if row["expires_at"]<=int(time.time()):
                raise AudioError("audio_upload_expired",409)
            pid,eid=row["project_id"],row["episode_id"]
            expected=_duration(db,pid,eid)
            root=_root(db_path)
            temp=root/(uid+".part")
            if temp.is_symlink() or not temp.is_file():
                raise AudioError("audio_upload_storage_missing",409)
            if temp.stat().st_size!=row["size_bytes"] or (
                _file_digest(temp)!=row["file_sha256"]):
                raise AudioError("audio_file_checksum_mismatch",422)
            with temp.open("rb") as stream:
                if stream.read(4)!=b"RIFF":
                    raise AudioError("audio_not_wav",422)
                stream.seek(8)
                if stream.read(4)!=b"WAVE":
                    raise AudioError("audio_not_wav",422)
            info=probe_wav(temp)
            if abs(info["duration_seconds"]-expected)>.25:
                raise AudioError("audio_episode_duration_mismatch",422)
            aid="AUD_"+secrets.token_hex(16)
            target=root/(aid+".wav")
            temp.rename(target)
            try:
                with transaction(db):
                    revision=db.execute("SELECT COALESCE(MAX(revision),0)+1 "
                        "FROM studio_audio_stems WHERE project_id=? AND "
                        "episode_id=? AND stem=?",
                        (pid,eid,row["stem"])).fetchone()[0]
                    db.execute("INSERT INTO studio_audio_stems("
                        "audio_id,project_id,episode_id,stem,revision,rights_ref,"
                        "sha256,size_bytes,duration_seconds,sample_rate,channels,"
                        "codec,status,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'in_review',?)",
                        (aid,pid,eid,row["stem"],revision,row["rights_ref"],
                         row["file_sha256"],row["size_bytes"],
                         info["duration_seconds"],info["sample_rate"],
                         info["channels"],info["codec"],int(time.time())))
                    db.execute("DELETE FROM studio_audio_uploads WHERE upload_id=?",(uid,))
                    _audit(db,who,"audio.stem_imported",aid,{
                        "project_id":pid,"episode_id":eid,"stem":row["stem"],
                        "revision":revision,"sha256":row["file_sha256"],
                        "rights_evidence_recorded":True,"status":"in_review"})
            except BaseException:
                target.rename(temp)
                raise
            return {"ok":True,"audio_id":aid,"revision":revision,
                    "status":"in_review","sha256":row["file_sha256"],
                    "gpu_action":False}


def list_stems(db_path,project,episode):
    with closing(open_db(db_path,initialize=False)) as db:
        pid,eid=_scope(db,project,episode)
        rows=db.execute("SELECT * FROM studio_audio_stems WHERE "
            "project_id=? AND episode_id=? "
            "ORDER BY stem,revision DESC LIMIT 150",(pid,eid)).fetchall()
        latest={}
        for row in rows:
            if row["stem"] not in latest:latest[row["stem"]]=row["revision"]
        tracks=[]
        for row in rows:
            values={k:row[k] for k in (
                "audio_id","project_id","episode_id","stem","revision",
                "sha256","size_bytes","duration_seconds","sample_rate",
                "channels","codec","status","review_reason","reviewer",
                "created_at","reviewed_at")}
            values["source_current"]=row["revision"]==latest[row["stem"]]
            values["rights_evidence_recorded"]=bool(row["rights_ref"])
            tracks.append(values)
        return {"ok":True,"project_id":pid,"episode_id":eid,
            "tracks":tracks,"gpu_action":False}


def get_stem_file(db_path,project,episode,audio_id):
    aid=_uid(audio_id,"AUD_")
    with closing(open_db(db_path,initialize=False)) as db:
        pid,eid=_scope(db,project,episode)
        row=db.execute("SELECT size_bytes FROM studio_audio_stems "
            "WHERE project_id=? AND episode_id=? AND audio_id=?",
            (pid,eid,aid)).fetchone()
        if row is None:raise AudioError("audio_stem_not_found",404)
        path=_root(db_path)/(aid+".wav")
        if path.is_symlink() or not path.is_file() or (
            path.stat().st_size!=row["size_bytes"]):
            raise AudioError("audio_storage_mismatch",503)
        return path,row["size_bytes"]


def review(db_path,data,actor):
    _fields(data,("project_id","episode_id","audio_id","decision","rationale",
                  "rights_verified"))
    who=_actor(actor)
    if data["decision"] not in ("approve","reject") or not isinstance(
        data["rationale"],str) or not 8<=len(data["rationale"].strip())<=600:
        raise AudioError("audio_review_reason_required")
    if data["decision"]=="approve" and data["rights_verified"] is not True:
        raise AudioError("audio_rights_verification_required",409)
    aid=_uid(data["audio_id"],"AUD_")
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise AudioError("audit_integrity_failure",409)
        pid,eid=_scope(db,data["project_id"],data["episode_id"])
        with transaction(db):
            row=db.execute("SELECT * FROM studio_audio_stems WHERE "
                "audio_id=? AND project_id=? AND episode_id=?",
                (aid,pid,eid)).fetchone()
            if row is None:raise AudioError("audio_stem_not_found",404)
            if row["status"]!="in_review":
                raise AudioError("audio_stem_already_reviewed",409)
            if data["decision"]=="approve":
                newer=db.execute("SELECT MAX(revision) FROM studio_audio_stems "
                    "WHERE project_id=? AND episode_id=? AND stem=?",
                    (pid,eid,row["stem"])).fetchone()[0]
                if row["revision"]!=newer:
                    raise AudioError("audio_revision_stale",409)
                path=_root(db_path)/(aid+".wav")
                if path.is_symlink() or not path.is_file() or (
                    path.stat().st_size!=row["size_bytes"] or
                    _file_digest(path)!=row["sha256"]):
                    raise AudioError("audio_storage_mismatch",503)
            state={"approve":"approved","reject":"rejected"}[data["decision"]]
            db.execute("UPDATE studio_audio_stems SET status=?,"
                "review_reason=?,reviewer=?,reviewed_at=? WHERE audio_id=?",
                (state,data["rationale"].strip(),who,int(time.time()),aid))
            _audit(db,who,"audio.stem_"+data["decision"],aid,{
                "project_id":pid,"episode_id":eid,"stem":row["stem"],
                "revision":row["revision"],"sha256":row["sha256"],
                "rights_verified":data["rights_verified"] is True,
                "status":state})
        return {"ok":True,"audio_id":aid,"status":state,"gpu_action":False}
