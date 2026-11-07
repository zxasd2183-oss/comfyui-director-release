"""Versioned SRT captions with strict timing, private text and human review.

No online transcription or generated creative dialogue; owner provides actual
script captions and evidence. All cues must fit real approved episode duration.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
from contextlib import closing

from production_core import open_db,transaction,verify_chain,_audit,_ident,ProductionError
from video_results import _file_digest

LANGS=frozenset(("zh-CN","zh-TW","en-US","ja-JP"))
ID=re.compile(r"^SUB_[a-f0-9]{32}$")
TIME=re.compile(r"^(\d{2}):([0-5]\d):([0-5]\d),(\d{3})$")
MAX_SOURCE=300
MAX_CHARS=90000


class SubtitleError(ValueError):
    def __init__(self,reason,status=400):
        self.reason,self.status=reason,status
        super().__init__(reason)


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS studio_subtitle_tracks(
      subtitle_id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,episode_id TEXT NOT NULL,
      language TEXT NOT NULL,revision INTEGER NOT NULL,
      content_sha256 TEXT NOT NULL,cue_count INTEGER NOT NULL,
      source_ref TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('in_review','approved','rejected')),
      reviewer TEXT,review_reason TEXT,
      created_at INTEGER NOT NULL,reviewed_at INTEGER,
      UNIQUE(project_id,episode_id,language,revision),
      FOREIGN KEY(project_id,episode_id) REFERENCES episodes(project_id,episode_id)
    );
    CREATE INDEX IF NOT EXISTS idx_subtitle_episode
      ON studio_subtitle_tracks(project_id,episode_id,language,revision);
    """)


def _scope(db,project,episode):
    try:pid,eid=_ident(project),_ident(episode)
    except ProductionError:raise SubtitleError("invalid_subtitle_scope") from None
    if db.execute("SELECT 1 FROM episodes WHERE project_id=? "
                  "AND episode_id=?",(pid,eid)).fetchone() is None:
        raise SubtitleError("subtitle_episode_not_found",404)
    return pid,eid


def _root(db_path,create=False):
    root=Path(db_path).parent/"subtitle_tracks"
    if root.is_symlink():raise SubtitleError("unsafe_subtitle_storage",503)
    if create:root.mkdir(mode=0o700,exist_ok=True)
    if not root.is_dir() or root.stat().st_mode&0o077:
        raise SubtitleError("unsafe_subtitle_storage",503)
    return root


def _stamp(value):
    found=TIME.fullmatch(value)
    if not found:raise SubtitleError("invalid_subtitle_timestamp",422)
    h,m,s,ms=map(int,found.groups())
    return ((h*60+m)*60+s)*1000+ms


def validate_srt(text,episode_ms):
    if not isinstance(text,str) or not 1<=len(text)<=MAX_CHARS:
        raise SubtitleError("invalid_subtitle_length",413)
    normalized=text.lstrip("\ufeff").replace("\r\n","\n").replace("\r","\n").strip()
    if "\x00" in normalized or any(
        ord(c)<32 and c not in "\n\t" for c in normalized):
        raise SubtitleError("invalid_subtitle_control_chars",422)
    blocks=re.split(r"\n[ \t]*\n",normalized)
    if not 1<=len(blocks)<=800:
        raise SubtitleError("invalid_subtitle_cue_count",422)
    previous=0
    for number,block in enumerate(blocks,1):
        lines=block.split("\n")
        if len(lines)<3 or lines[0].strip()!=str(number):
            raise SubtitleError("subtitle_sequence_invalid",422)
        parts=lines[1].split(" --> ")
        if len(parts)!=2:
            raise SubtitleError("subtitle_timing_invalid",422)
        start,end=map(_stamp,parts)
        if not 0<=start<end<=episode_ms or start<previous:
            raise SubtitleError("subtitle_outside_episode_or_overlapping",422)
        caption="\n".join(lines[2:])
        if not 1<=len(caption.strip())<=240:
            raise SubtitleError("subtitle_cue_text_invalid",422)
        if "<" in caption or ">" in caption or "{" in caption or "}" in caption:
            raise SubtitleError("subtitle_markup_not_supported",422)
        previous=end
    return normalized+"\n",len(blocks)


def _duration_ms(db,pid,eid):
    rows=db.execute("SELECT duration_ms FROM production_shots "
        "WHERE project_id=? AND episode_id=?",(pid,eid)).fetchall()
    if not rows or len(rows)>500:
        raise SubtitleError("subtitle_episode_shots_missing",409)
    return sum(r["duration_ms"] for r in rows)


def save(db_path,data,actor):
    required={"project_id","episode_id","language","text","source_ref"}
    if not isinstance(data,dict) or set(data)!=required:
        raise SubtitleError("invalid_subtitle_fields")
    if not isinstance(actor,str) or not 1<=len(actor)<=160:
        raise SubtitleError("invalid_subtitle_actor")
    lang=data["language"]
    if not isinstance(lang,str) or lang not in LANGS:
        raise SubtitleError("subtitle_language_not_supported")
    source=data["source_ref"]
    if not isinstance(source,str) or not 8<=len(source.strip())<=MAX_SOURCE or (
        any(ord(c)<32 for c in source)):
        raise SubtitleError("subtitle_source_evidence_required")
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        if not verify_chain(db):
            raise SubtitleError("audit_integrity_failure",409)
        pid,eid=_scope(db,data["project_id"],data["episode_id"])
        normalized,count=validate_srt(data["text"],_duration_ms(db,pid,eid))
        raw=normalized.encode("utf-8")
        digest=hashlib.sha256(raw).hexdigest()
        folder=_root(db_path,create=True)
        with transaction(db):
            old=db.execute("SELECT subtitle_id,status FROM studio_subtitle_tracks "
                "WHERE project_id=? AND episode_id=? AND language=? "
                "AND content_sha256=? AND source_ref=? ORDER BY revision DESC LIMIT 1",
                (pid,eid,lang,digest,source.strip())).fetchone()
            if old:
                file=folder/(old["subtitle_id"]+".srt")
                if file.is_symlink() or not file.is_file() or _file_digest(file)!=digest:
                    raise SubtitleError("subtitle_storage_mismatch",503)
                return {"ok":True,"subtitle_id":old["subtitle_id"],
                    "status":old["status"],"already_imported":True,
                    "gpu_action":False}
            uid="SUB_"+secrets.token_hex(16)
            path=folder/(uid+".srt")
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                with os.fdopen(fd,"wb") as file:
                    fd=None
                    file.write(raw)
                    file.flush();os.fsync(file.fileno())
                version=db.execute("SELECT COALESCE(MAX(revision),0)+1 "
                    "FROM studio_subtitle_tracks WHERE project_id=? "
                    "AND episode_id=? AND language=?",
                    (pid,eid,lang)).fetchone()[0]
                db.execute("INSERT INTO studio_subtitle_tracks("
                    "subtitle_id,project_id,episode_id,language,revision,"
                    "content_sha256,cue_count,source_ref,status,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,'in_review',?)",
                    (uid,pid,eid,lang,version,digest,count,source.strip(),
                     int(time.time())))
                _audit(db,actor,"subtitle.imported",uid,{
                    "project_id":pid,"episode_id":eid,"language":lang,
                    "revision":version,"cue_count":count,
                    "content_sha256":digest,"source_evidence_recorded":True})
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            finally:
                if fd is not None:os.close(fd)
            return {"ok":True,"subtitle_id":uid,"revision":version,
                "cue_count":count,"status":"in_review","gpu_action":False}


def list_tracks(db_path,project,episode):
    with closing(open_db(db_path,initialize=False)) as db:
        pid,eid=_scope(db,project,episode)
        rows=db.execute("SELECT * FROM studio_subtitle_tracks "
            "WHERE project_id=? AND episode_id=? "
            "ORDER BY language,revision DESC LIMIT 150",
            (pid,eid)).fetchall()
        latest={}
        for row in rows:
            if row["language"] not in latest:latest[row["language"]]=row["revision"]
        return {"ok":True,"project_id":pid,"episode_id":eid,
            "subtitles":[{**{k:row[k] for k in (
                "subtitle_id","project_id","episode_id","language",
                "revision","content_sha256","cue_count","status",
                "review_reason","reviewer","created_at","reviewed_at")},
                "source_current":row["revision"]==latest[row["language"]],
                "source_evidence_recorded":bool(row["source_ref"])}
                for row in rows],"gpu_action":False}


def get_file(db_path,project,episode,subtitle_id):
    if not isinstance(subtitle_id,str) or not ID.fullmatch(subtitle_id):
        raise SubtitleError("invalid_subtitle_id")
    with closing(open_db(db_path,initialize=False)) as db:
        pid,eid=_scope(db,project,episode)
        row=db.execute("SELECT content_sha256 FROM studio_subtitle_tracks "
            "WHERE project_id=? AND episode_id=? AND subtitle_id=?",
            (pid,eid,subtitle_id)).fetchone()
        if row is None:raise SubtitleError("subtitle_not_found",404)
        path=_root(db_path)/(subtitle_id+".srt")
        if path.is_symlink() or not path.is_file() or (
            path.stat().st_size>MAX_CHARS*4+4 or
            _file_digest(path)!=row["content_sha256"]):
            raise SubtitleError("subtitle_storage_mismatch",503)
        return path


def review(db_path,data,actor):
    fields={"project_id","episode_id","subtitle_id","decision",
            "rationale","text_rights_verified"}
    if not isinstance(data,dict) or set(data)!=fields:
        raise SubtitleError("invalid_subtitle_review_fields")
    if data["decision"] not in ("approve","reject") or not isinstance(
        data["rationale"],str) or not 8<=len(data["rationale"].strip())<=600:
        raise SubtitleError("subtitle_review_reason_required")
    if data["decision"]=="approve" and data["text_rights_verified"] is not True:
        raise SubtitleError("subtitle_text_rights_verification_required",409)
    if not isinstance(actor,str) or not 1<=len(actor)<=160:
        raise SubtitleError("invalid_subtitle_actor")
    uid=data["subtitle_id"]
    if not isinstance(uid,str) or not ID.fullmatch(uid):
        raise SubtitleError("invalid_subtitle_id")
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise SubtitleError("audit_integrity_failure",409)
        pid,eid=_scope(db,data["project_id"],data["episode_id"])
        with transaction(db):
            row=db.execute("SELECT * FROM studio_subtitle_tracks WHERE "
                "subtitle_id=? AND project_id=? AND episode_id=?",
                (uid,pid,eid)).fetchone()
            if row is None:raise SubtitleError("subtitle_not_found",404)
            if row["status"]!="in_review":
                raise SubtitleError("subtitle_already_reviewed",409)
            if data["decision"]=="approve":
                latest=db.execute("SELECT MAX(revision) FROM studio_subtitle_tracks "
                    "WHERE project_id=? AND episode_id=? AND language=?",
                    (pid,eid,row["language"])).fetchone()[0]
                if latest!=row["revision"]:
                    raise SubtitleError("subtitle_revision_stale",409)
                path=_root(db_path)/(uid+".srt")
                if path.is_symlink() or not path.is_file() or (
                    _file_digest(path)!=row["content_sha256"]):
                    raise SubtitleError("subtitle_storage_mismatch",503)
            state={"approve":"approved","reject":"rejected"}[data["decision"]]
            db.execute("UPDATE studio_subtitle_tracks SET status=?,"
                "reviewer=?,review_reason=?,reviewed_at=? WHERE subtitle_id=?",
                (state,actor,data["rationale"].strip(),int(time.time()),uid))
            _audit(db,actor,"subtitle."+data["decision"],uid,{
                "project_id":pid,"episode_id":eid,"language":row["language"],
                "revision":row["revision"],"sha256":row["content_sha256"],
                "text_rights_verified":data["text_rights_verified"] is True,
                "status":state})
        return {"ok":True,"subtitle_id":uid,"status":state,"gpu_action":False}
