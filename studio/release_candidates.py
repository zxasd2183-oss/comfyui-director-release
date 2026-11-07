"""Private release candidate with approved current Chinese subtitles.

Does not publish to users, streaming platforms or anyone else. Local CPU
ffmpeg losslessly copies approved A/V streams and muxes reviewed SRT as
mov_text. Final owner QC and rights signoff remain explicit independent gates.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from contextlib import closing

from production_core import open_db,transaction,verify_chain,_audit,_ident,ProductionError
from audio_master import readiness as master_readiness, get_file as get_master_file
from subtitle_tracks import _root as subtitle_root
from video_results import _file_digest

ID=re.compile(r"^REL_[a-f0-9]{32}$")


class ReleaseError(ValueError):
    def __init__(self,reason,status=400):
        self.reason,self.status=reason,status
        super().__init__(reason)


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS studio_release_candidates(
      release_id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,episode_id TEXT NOT NULL,
      source_manifest_sha256 TEXT NOT NULL,source_manifest_json TEXT NOT NULL,
      file_sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,
      duration_seconds REAL NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('in_review','approved','rejected')),
      review_reason TEXT,reviewer TEXT,
      created_at INTEGER NOT NULL,reviewed_at INTEGER,
      FOREIGN KEY(project_id,episode_id) REFERENCES episodes(project_id,episode_id)
    );
    CREATE INDEX IF NOT EXISTS idx_release_episode
      ON studio_release_candidates(project_id,episode_id,created_at);
    """)


def _scope(project,episode):
    try:return _ident(project),_ident(episode)
    except ProductionError:raise ReleaseError("invalid_release_scope") from None


def _root(db_path,create=False):
    folder=Path(db_path).parent/"release_candidates"
    if folder.is_symlink():raise ReleaseError("unsafe_release_storage",503)
    if create:folder.mkdir(mode=0o700,exist_ok=True)
    if not folder.is_dir() or folder.stat().st_mode&0o077:
        raise ReleaseError("unsafe_release_storage",503)
    return folder


def readiness(db_path,project,episode):
    pid,eid=_scope(project,episode)
    sources=master_readiness(db_path,pid,eid)
    blockers=[]
    with closing(open_db(db_path,initialize=False)) as db:
        if db.execute("SELECT 1 FROM episodes WHERE project_id=? "
                      "AND episode_id=?",(pid,eid)).fetchone() is None:
            raise ReleaseError("episode_not_found",404)
        masters=db.execute("SELECT master_id,source_manifest_sha256,"
            "file_sha256,size_bytes,duration_seconds FROM studio_av_masters "
            "WHERE project_id=? AND episode_id=? AND status='approved' "
            "ORDER BY reviewed_at DESC,created_at DESC,master_id DESC LIMIT 40",
            (pid,eid)).fetchall()
        approved=next((m for m in masters if
            m["source_manifest_sha256"]==sources["source_manifest_sha256"]),None)
        if not sources["ready"] or approved is None:
            blockers.append("current_av_master_not_approved")
        row=db.execute("SELECT subtitle_id,language,revision,content_sha256,"
            "cue_count,source_ref,status,reviewer FROM studio_subtitle_tracks "
            "WHERE project_id=? AND episode_id=? AND language='zh-CN' "
            "ORDER BY revision DESC LIMIT 1",(pid,eid)).fetchone()
        if row is None:
            blockers.append("chinese_subtitles_missing")
        elif row["status"]!="approved" or not row["reviewer"] or not row["source_ref"]:
            blockers.append("chinese_subtitles_not_approved")
        subt={"subtitle_id":row["subtitle_id"],"language":"zh-CN",
            "revision":row["revision"],"content_sha256":row["content_sha256"],
            "cue_count":row["cue_count"],"rights_evidence_human_checked":True} if (
                row and row["status"]=="approved" and row["reviewer"]) else None
        pic={"master_id":approved["master_id"],
            "file_sha256":approved["file_sha256"],
            "size_bytes":approved["size_bytes"],
            "duration_seconds":approved["duration_seconds"],
            "source_manifest_sha256":approved["source_manifest_sha256"]} if approved else None
        manifest={"schema":"director_studio_release_candidate_v1",
            "project_id":pid,"episode_id":eid,
            "av_master":pic,"subtitle_track":subt,
            "release_requires_owner_manual_final_qc":True,
            "automatic_publication":False}
        digest=hashlib.sha256(json.dumps(manifest,sort_keys=True,
            ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
        return {"ok":True,"project_id":pid,"episode_id":eid,
            "ready":not blockers,"blocked":blockers,
            "source_manifest":manifest,"source_manifest_sha256":digest,
            "publicly_released":False,"gpu_action":False}


def _verify(path,digest,size=None):
    if path.is_symlink() or not path.is_file() or (
        size is not None and path.stat().st_size!=size) or (
            _file_digest(path)!=digest):
        raise ReleaseError("release_source_storage_mismatch",409)


def _probe(path,runner):
    try:
        reply=runner(["/usr/bin/ffprobe","-v","error",
            "-show_entries","format=format_name,duration:"
               "stream=codec_type,codec_name,width,height",
            "-of","json",str(path)],capture_output=True,timeout=25,check=False)
        if reply.returncode or len(reply.stdout)>64000:raise ValueError
        data=json.loads(reply.stdout)
        streams=data["streams"]
        count={t:sum(row.get("codec_type")==t for row in streams)
               for t in ("video","audio","subtitle")}
        subtitle=next(row for row in streams
                      if row.get("codec_type")=="subtitle")
        if count!={"video":1,"audio":1,"subtitle":1} or (
            subtitle["codec_name"]!="mov_text"):
            raise ValueError
        seconds=float(data["format"]["duration"])
        if "mp4" not in data["format"]["format_name"].split(",") or (
            not .1<=seconds<=3600):
            raise ValueError
        return {"duration_seconds":seconds}
    except (OSError,ValueError,KeyError,TypeError,IndexError,
            subprocess.TimeoutExpired,json.JSONDecodeError,StopIteration):
        raise ReleaseError("release_candidate_probe_failed",422) from None


def mux(db_path,project,episode,actor,runner=None):
    if not isinstance(actor,str) or not 1<=len(actor)<=160:
        raise ReleaseError("invalid_release_actor")
    run=subprocess.run if runner is None else runner
    inputs=readiness(db_path,project,episode)
    if not inputs["ready"]:
        raise ReleaseError("release_sources_not_approved",409)
    pid,eid=inputs["project_id"],inputs["episode_id"]
    manifest=inputs["source_manifest"]
    master=manifest["av_master"]
    subtitle=manifest["subtitle_track"]
    master_path,_=get_master_file(db_path,pid,eid,master["master_id"])
    srt_path=subtitle_root(db_path)/(subtitle["subtitle_id"]+".srt")
    _verify(master_path,master["file_sha256"],master["size_bytes"])
    _verify(srt_path,subtitle["content_sha256"])
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        if not verify_chain(db):
            raise ReleaseError("audit_integrity_failure",409)
        previous=db.execute("SELECT * FROM studio_release_candidates WHERE "
            "project_id=? AND episode_id=? AND source_manifest_sha256=? "
            "ORDER BY created_at DESC LIMIT 1",
            (pid,eid,inputs["source_manifest_sha256"])).fetchone()
        if previous:
            file=_root(db_path)/(previous["release_id"]+".mp4")
            _verify(file,previous["file_sha256"],previous["size_bytes"])
            return {"ok":True,"release_id":previous["release_id"],
                "already_muxed":True,"status":previous["status"],
                "publicly_released":False,"gpu_action":False}
    storage=_root(db_path,create=True)
    if shutil.disk_usage(storage).free<master["size_bytes"]+100_000_000:
        raise ReleaseError("release_storage_space_insufficient",507)
    uid="REL_"+secrets.token_hex(16)
    final=storage/(uid+".mp4")
    fd,temporary=tempfile.mkstemp(prefix=".release-candidate-",
         suffix=".mp4",dir=str(storage))
    os.close(fd)
    published=False
    try:
        try:
            result=run(["/usr/bin/ffmpeg","-nostdin","-hide_banner",
                "-loglevel","error","-i",str(master_path),
                "-i",str(srt_path),"-map","0:v:0","-map","0:a:0",
                "-map","1:s:0","-c:v","copy","-c:a","copy",
                "-c:s","mov_text","-metadata:s:s:0","language=zho",
                "-movflags","+faststart","-y",temporary],
                capture_output=True,check=False,timeout=3600)
        except (OSError,subprocess.TimeoutExpired):
            raise ReleaseError("release_ffmpeg_unavailable",503) from None
        if result.returncode or not Path(temporary).is_file() or (
            Path(temporary).stat().st_size<128):
            raise ReleaseError("release_ffmpeg_mux_failed",422)
        info=_probe(temporary,run)
        if abs(info["duration_seconds"]-master["duration_seconds"])>.35:
            raise ReleaseError("release_duration_mismatch",422)
        current=readiness(db_path,pid,eid)
        if not current["ready"] or (
            current["source_manifest_sha256"]!=inputs["source_manifest_sha256"]):
            raise ReleaseError("release_sources_changed_during_mux",409)
        _verify(master_path,master["file_sha256"],master["size_bytes"])
        _verify(srt_path,subtitle["content_sha256"])
        media_sha=_file_digest(Path(temporary))
        media_size=Path(temporary).stat().st_size
        os.link(temporary,final)
        published=True
        with closing(open_db(db_path)) as db:
            if not verify_chain(db):
                raise ReleaseError("audit_integrity_failure",409)
            with transaction(db):
                db.execute("INSERT INTO studio_release_candidates("
                    "release_id,project_id,episode_id,source_manifest_sha256,"
                    "source_manifest_json,file_sha256,size_bytes,"
                    "duration_seconds,status,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,'in_review',?)",
                    (uid,pid,eid,inputs["source_manifest_sha256"],
                     json.dumps(manifest,sort_keys=True,ensure_ascii=False),
                     media_sha,media_size,info["duration_seconds"],
                     int(time.time())))
                _audit(db,actor,"release.candidate_muxed",uid,{
                    "project_id":pid,"episode_id":eid,
                    "master_id":master["master_id"],
                    "subtitle_id":subtitle["subtitle_id"],
                    "source_sha256":inputs["source_manifest_sha256"],
                    "file_sha256":media_sha,"status":"in_review",
                    "publicly_released":False,"gpu_action":False})
        return {"ok":True,"release_id":uid,"status":"in_review",
            "file_sha256":media_sha,"size_bytes":media_size,
            "publicly_released":False,"gpu_action":False}
    except BaseException:
        if published:final.unlink(missing_ok=True)
        raise
    finally:
        Path(temporary).unlink(missing_ok=True)


def list_candidates(db_path,project,episode):
    pid,eid=_scope(project,episode)
    with closing(open_db(db_path,initialize=False)) as db:
        if db.execute("SELECT 1 FROM episodes WHERE project_id=? "
                      "AND episode_id=?",(pid,eid)).fetchone() is None:
            raise ReleaseError("episode_not_found",404)
        rows=db.execute("SELECT release_id,source_manifest_sha256,"
            "source_manifest_json,file_sha256,size_bytes,duration_seconds,"
            "status,review_reason,reviewer,created_at,reviewed_at "
            "FROM studio_release_candidates WHERE project_id=? AND episode_id=? "
            "ORDER BY created_at DESC LIMIT 30",(pid,eid)).fetchall()
        current=readiness(db_path,pid,eid)["source_manifest_sha256"]
        candidates=[]
        for row in rows:
            value=dict(row)
            manifest=json.loads(value.pop("source_manifest_json"))
            sub=manifest.get("subtitle_track") or {}
            value["subtitle_id"]=sub.get("subtitle_id")
            value["subtitle_language"]=sub.get("language")
            value["source_current"]=row["source_manifest_sha256"]==current
            candidates.append(value)
        return {"ok":True,"project_id":pid,"episode_id":eid,
            "candidates":candidates,
            "publicly_released":False,"gpu_action":False}


def get_file(db_path,project,episode,release_id):
    pid,eid=_scope(project,episode)
    if not isinstance(release_id,str) or not ID.fullmatch(release_id):
        raise ReleaseError("invalid_release_id")
    with closing(open_db(db_path,initialize=False)) as db:
        row=db.execute("SELECT size_bytes FROM studio_release_candidates "
            "WHERE project_id=? AND episode_id=? AND release_id=?",
            (pid,eid,release_id)).fetchone()
        if row is None:raise ReleaseError("release_candidate_not_found",404)
        file=_root(db_path)/(release_id+".mp4")
        if file.is_symlink() or not file.is_file() or (
            file.stat().st_size!=row["size_bytes"]):
            raise ReleaseError("release_storage_mismatch",503)
        return file,row["size_bytes"]


def review(db_path,data,actor):
    fields={"project_id","episode_id","release_id","decision","rationale",
            "all_media_checked","subtitle_checked","rights_checked",
            "final_playback_checked"}
    if not isinstance(data,dict) or set(data)!=fields:
        raise ReleaseError("invalid_release_review_fields")
    if data["decision"] not in ("approve","reject") or not isinstance(
        data["rationale"],str) or not 8<=len(data["rationale"].strip())<=600:
        raise ReleaseError("release_review_reason_required")
    if data["decision"]=="approve" and not all(
        data[k] is True for k in (
            "all_media_checked","subtitle_checked","rights_checked",
            "final_playback_checked")):
        raise ReleaseError("release_final_qc_confirmation_required",409)
    if not isinstance(actor,str) or not 1<=len(actor)<=160:
        raise ReleaseError("invalid_release_actor")
    pid,eid=_scope(data["project_id"],data["episode_id"])
    uid=data["release_id"]
    if not isinstance(uid,str) or not ID.fullmatch(uid):
        raise ReleaseError("invalid_release_id")
    current=readiness(db_path,pid,eid)
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise ReleaseError("audit_integrity_failure",409)
        with transaction(db):
            row=db.execute("SELECT * FROM studio_release_candidates "
                "WHERE project_id=? AND episode_id=? AND release_id=?",
                (pid,eid,uid)).fetchone()
            if row is None:raise ReleaseError("release_candidate_not_found",404)
            if row["status"]!="in_review":
                raise ReleaseError("release_candidate_already_reviewed",409)
            if data["decision"]=="approve":
                if not current["ready"] or (
                    row["source_manifest_sha256"]!=current["source_manifest_sha256"]):
                    raise ReleaseError("release_sources_outdated",409)
                file=_root(db_path)/(uid+".mp4")
                _verify(file,row["file_sha256"],row["size_bytes"])
            status={"approve":"approved","reject":"rejected"}[data["decision"]]
            db.execute("UPDATE studio_release_candidates SET status=?,"
                "review_reason=?,reviewer=?,reviewed_at=? WHERE release_id=?",
                (status,data["rationale"].strip(),actor,int(time.time()),uid))
            _audit(db,actor,"release.candidate_"+data["decision"],uid,{
                "project_id":pid,"episode_id":eid,
                "source_sha256":row["source_manifest_sha256"],
                "file_sha256":row["file_sha256"],"status":status,
                "qc_checks":[key for key in (
                    "all_media_checked","subtitle_checked",
                    "rights_checked","final_playback_checked")
                    if data[key] is True],
                "publicly_released":False})
        return {"ok":True,"release_id":uid,"status":status,
            "publicly_released":False,"gpu_action":False}
