"""Audited owner-reviewed audio/video master, using local CPU FFmpeg only.

Requires one CURRENT approved picture cut and all three CURRENT approved,
copyright-verified WAV stems (dialogue/music/effects). Copies video and mixes
PCM stems to AAC with loudness normalization; never claims final release.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing

from production_core import open_db, transaction, verify_chain, _audit, _ident, ProductionError
from picture_cuts import get_readiness as picture_readiness, get_cut_file
from audio_stems import _root as audio_root, STEMS
from video_results import _file_digest

MASTER_ID=re.compile(r"^MASTER_[a-f0-9]{32}$")


class MasterError(ValueError):
    def __init__(self,reason,status=400):
        self.reason,self.status=reason,status
        super().__init__(reason)


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS studio_av_masters(
        master_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,episode_id TEXT NOT NULL,
        source_manifest_sha256 TEXT NOT NULL,
        source_manifest_json TEXT NOT NULL,
        file_sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,
        duration_seconds REAL NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('in_review','approved','rejected')),
        review_reason TEXT,reviewer TEXT,
        created_at INTEGER NOT NULL,reviewed_at INTEGER,
        FOREIGN KEY(project_id,episode_id) REFERENCES episodes(project_id,episode_id)
    );
    CREATE INDEX IF NOT EXISTS idx_av_master_episode
      ON studio_av_masters(project_id,episode_id,created_at);
    """)


def _ids(project,episode):
    try:return _ident(project),_ident(episode)
    except ProductionError:
        raise MasterError("invalid_master_scope") from None


def _store(db_path,create=False):
    root=Path(db_path).parent/"av_masters"
    if root.is_symlink():raise MasterError("unsafe_master_storage",503)
    if create:root.mkdir(mode=0o700,exist_ok=True)
    if not root.is_dir() or root.stat().st_mode&0o077:
        raise MasterError("unsafe_master_storage",503)
    return root


def readiness(db_path,project,episode):
    pid,eid=_ids(project,episode)
    picture=picture_readiness(db_path,pid,eid)
    blockers=[]
    with closing(open_db(db_path,initialize=False)) as db:
        if db.execute("SELECT 1 FROM episodes WHERE project_id=? AND episode_id=?",
                      (pid,eid)).fetchone() is None:
            raise MasterError("episode_not_found",404)
        approved=db.execute("SELECT cut_id,source_manifest_sha256,file_sha256,"
            "size_bytes,duration_seconds FROM studio_picture_cuts "
            "WHERE project_id=? AND episode_id=? AND status='approved' "
            "ORDER BY reviewed_at DESC,created_at DESC,cut_id DESC LIMIT 40",
            (pid,eid)).fetchall()
        picture_cut=next((row for row in approved
            if row["source_manifest_sha256"]==picture["source_manifest_sha256"]),None)
        if not picture["ready"] or picture_cut is None:
            blockers.append("current_approved_picture_cut_missing")
        stems=[]
        for stem in ("dialogue","music","effects"):
            row=db.execute("SELECT audio_id,revision,status,sha256,size_bytes,"
                "duration_seconds,rights_ref,reviewer FROM studio_audio_stems "
                "WHERE project_id=? AND episode_id=? AND stem=? "
                "ORDER BY revision DESC LIMIT 1",(pid,eid,stem)).fetchone()
            if row is None:
                blockers.append("approved_audio_stem_missing:"+stem)
            elif row["status"]!="approved" or not row["rights_ref"] or not row["reviewer"]:
                blockers.append("current_audio_stem_not_approved:"+stem)
            else:
                stems.append({"stem":stem,"audio_id":row["audio_id"],
                    "revision":row["revision"],"sha256":row["sha256"],
                    "size_bytes":row["size_bytes"],
                    "duration_seconds":row["duration_seconds"],
                    "rights_evidence_recorded":True,"rights_human_reviewed":True})
        cut={"cut_id":picture_cut["cut_id"],
             "sha256":picture_cut["file_sha256"],
             "size_bytes":picture_cut["size_bytes"],
             "duration_seconds":picture_cut["duration_seconds"],
             "source_manifest_sha256":picture_cut["source_manifest_sha256"]} if picture_cut else None
        manifest={"schema":"director_studio_av_master_v1",
            "project_id":pid,"episode_id":eid,
            "picture_cut":cut,"audio_stems":stems,
            "episode_duration_ms":picture["total_duration_ms"],
            "requires_final_release_approval":True}
        canonical=json.dumps(manifest,sort_keys=True,ensure_ascii=False,
            separators=(",",":")).encode()
        return {"ok":True,"project_id":pid,"episode_id":eid,
            "ready":not blockers,"blocked":blockers,
            "current_picture_cut":cut,
            "approved_audio_count":len(stems),
            "source_manifest_sha256":hashlib.sha256(canonical).hexdigest(),
            "source_manifest":manifest,"gpu_action":False}


def _verify_source(path,sha,size):
    if path.is_symlink() or not path.is_file() or (
        path.stat().st_size!=size or _file_digest(path)!=sha):
        raise MasterError("av_master_source_media_changed",409)


def _probe_mp4(file,runner):
    try:
        result=runner(["/usr/bin/ffprobe","-v","error",
           "-show_entries","format=format_name,duration:"
              "stream=codec_type,codec_name,sample_rate,channels,width,height",
           "-of","json",str(file)],capture_output=True,timeout=25,check=False)
        if result.returncode or len(result.stdout)>64000:raise ValueError
        obj=json.loads(result.stdout)
        if "mp4" not in obj["format"]["format_name"].split(","):
            raise ValueError
        video=[x for x in obj["streams"] if x["codec_type"]=="video"]
        sound=[x for x in obj["streams"] if x["codec_type"]=="audio"]
        duration=float(obj["format"]["duration"])
        if len(video)!=1 or len(sound)!=1 or (
            sound[0]["codec_name"]!="aac" or int(sound[0]["sample_rate"])!=48000 or
            int(sound[0]["channels"])!=2 or not .1<=duration<=3600):
            raise ValueError
        return {"duration_seconds":duration,"width":int(video[0]["width"]),
            "height":int(video[0]["height"])}
    except (ValueError,KeyError,TypeError,IndexError,OSError,
            subprocess.TimeoutExpired,json.JSONDecodeError):
        raise MasterError("av_master_output_ffprobe_failed",422) from None


def mix(db_path,project,episode,actor,runner=None):
    if not isinstance(actor,str) or not 1<=len(actor)<=160:
        raise MasterError("invalid_master_actor")
    run=subprocess.run if runner is None else runner
    pre=readiness(db_path,project,episode)
    if not pre["ready"]:
        raise MasterError("av_master_sources_not_approved",409)
    pid,eid=pre["project_id"],pre["episode_id"]
    sources=pre["source_manifest"]
    picture=sources["picture_cut"]
    pic_path,_=get_cut_file(db_path,pid,eid,picture["cut_id"])
    _verify_source(pic_path,picture["sha256"],picture["size_bytes"])
    tracks=[]
    for track in sources["audio_stems"]:
        path=audio_root(db_path)/(track["audio_id"]+".wav")
        _verify_source(path,track["sha256"],track["size_bytes"])
        if abs(track["duration_seconds"]-picture["duration_seconds"])>.25:
            raise MasterError("av_master_track_duration_mismatch",409)
        tracks.append(path)

    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        if not verify_chain(db):
            raise MasterError("audit_integrity_failure",409)
        existing=db.execute("SELECT * FROM studio_av_masters "
            "WHERE project_id=? AND episode_id=? AND source_manifest_sha256=? "
            "ORDER BY created_at DESC LIMIT 1",
            (pid,eid,pre["source_manifest_sha256"])).fetchone()
        if existing:
            location=_store(db_path)/(existing["master_id"]+".mp4")
            _verify_source(location,existing["file_sha256"],existing["size_bytes"])
            return {"ok":True,"already_mixed":True,
                "master_id":existing["master_id"],"status":existing["status"],
                "gpu_action":False}
    target_root=_store(db_path,create=True)
    total=sum(x["size_bytes"] for x in sources["audio_stems"])+picture["size_bytes"]
    if shutil.disk_usage(target_root).free<total+100_000_000:
        raise MasterError("av_master_storage_space_insufficient",507)
    uid="MASTER_"+secrets.token_hex(16)
    target=target_root/(uid+".mp4")
    handle,temp=tempfile.mkstemp(prefix=".av-staging-",suffix=".mp4",
                                 dir=str(target_root))
    os.close(handle)
    published=False
    try:
        cmd=["/usr/bin/ffmpeg","-nostdin","-hide_banner","-loglevel","error",
             "-i",str(pic_path)]
        for track in tracks:cmd.extend(["-i",str(track)])
        cmd.extend(["-filter_complex",
             "[1:a:0][2:a:0][3:a:0]amix=inputs=3:duration=longest:"
             "dropout_transition=0:normalize=0,"
             "loudnorm=I=-16:TP=-1.5:LRA=11[a]",
             "-map","0:v:0","-map","[a]",
             "-c:v","copy","-c:a","aac","-b:a","256k",
             "-ar","48000","-ac","2",
             "-t",f'{picture["duration_seconds"]:.6f}',
             "-movflags","+faststart","-y",temp])
        try:
            completed=run(cmd,capture_output=True,timeout=3600,check=False)
        except (OSError,subprocess.TimeoutExpired):
            raise MasterError("av_master_ffmpeg_unavailable",503) from None
        if completed.returncode or not Path(temp).is_file() or (
            Path(temp).stat().st_size<128):
            raise MasterError("av_master_ffmpeg_failed",422)
        result=_probe_mp4(temp,run)
        if abs(result["duration_seconds"]-picture["duration_seconds"])>.35:
            raise MasterError("av_master_duration_invalid",422)
        # All 4 current approved source revisions must still match after
        # CPU work, and all 4 original source files must retain their bytes.
        new=readiness(db_path,pid,eid)
        if not new["ready"] or (
            new["source_manifest_sha256"]!=pre["source_manifest_sha256"]):
            raise MasterError("av_master_sources_changed",409)
        _verify_source(pic_path,picture["sha256"],picture["size_bytes"])
        for track,path in zip(sources["audio_stems"],tracks):
            _verify_source(path,track["sha256"],track["size_bytes"])
        output_sha=_file_digest(Path(temp))
        output_bytes=Path(temp).stat().st_size
        os.link(temp,target)
        published=True
        with closing(open_db(db_path)) as db:
            if not verify_chain(db):
                raise MasterError("audit_integrity_failure",409)
            with transaction(db):
                db.execute("INSERT INTO studio_av_masters("
                    "master_id,project_id,episode_id,source_manifest_sha256,"
                    "source_manifest_json,file_sha256,size_bytes,"
                    "duration_seconds,status,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,'in_review',?)",
                    (uid,pid,eid,pre["source_manifest_sha256"],
                     json.dumps(sources,sort_keys=True,ensure_ascii=False),
                     output_sha,output_bytes,result["duration_seconds"],
                     int(time.time())))
                _audit(db,actor,"av.master_created",uid,{
                    "project_id":pid,"episode_id":eid,
                    "picture_cut_id":picture["cut_id"],
                    "audio_stems":[track["audio_id"] for track in sources["audio_stems"]],
                    "source_sha256":pre["source_manifest_sha256"],
                    "output_sha256":output_sha,"status":"in_review",
                    "gpu_action":False})
        return {"ok":True,"master_id":uid,"status":"in_review",
            "file_sha256":output_sha,"size_bytes":output_bytes,
            "gpu_action":False,"release_approved":False}
    except BaseException:
        if published:target.unlink(missing_ok=True)
        raise
    finally:
        Path(temp).unlink(missing_ok=True)


def list_masters(db_path,project,episode):
    pid,eid=_ids(project,episode)
    with closing(open_db(db_path,initialize=False)) as db:
        if db.execute("SELECT 1 FROM episodes WHERE "
            "project_id=? AND episode_id=?",(pid,eid)).fetchone() is None:
            raise MasterError("episode_not_found",404)
        rows=db.execute("SELECT master_id,source_manifest_sha256,"
            "file_sha256,size_bytes,duration_seconds,status,review_reason,"
            "reviewer,created_at,reviewed_at FROM studio_av_masters "
            "WHERE project_id=? AND episode_id=? "
            "ORDER BY created_at DESC LIMIT 30",(pid,eid)).fetchall()
        current=readiness(db_path,pid,eid)["source_manifest_sha256"]
        return {"ok":True,"project_id":pid,"episode_id":eid,
            "masters":[dict(r,source_current=(
                r["source_manifest_sha256"]==current)) for r in rows],
            "gpu_action":False}


def get_file(db_path,project,episode,master_id):
    pid,eid=_ids(project,episode)
    if not isinstance(master_id,str) or not MASTER_ID.fullmatch(master_id):
        raise MasterError("invalid_master_id")
    with closing(open_db(db_path,initialize=False)) as db:
        row=db.execute("SELECT size_bytes FROM studio_av_masters WHERE "
            "project_id=? AND episode_id=? AND master_id=?",
            (pid,eid,master_id)).fetchone()
        if row is None:raise MasterError("master_not_found",404)
        path=_store(db_path)/(master_id+".mp4")
        if path.is_symlink() or not path.is_file() or (
            path.stat().st_size!=row["size_bytes"]):
            raise MasterError("master_storage_mismatch",503)
        return path,row["size_bytes"]


def review(db_path,data,actor):
    fields={"project_id","episode_id","master_id","decision",
            "rationale","rights_verified","final_listen_completed"}
    if not isinstance(data,dict) or set(data)!=fields:
        raise MasterError("invalid_master_review_fields")
    pid,eid=_ids(data["project_id"],data["episode_id"])
    uid=data["master_id"]
    if not isinstance(uid,str) or not MASTER_ID.fullmatch(uid):
        raise MasterError("invalid_master_id")
    if data["decision"] not in ("approve","reject") or not isinstance(
        data["rationale"],str) or not 8<=len(data["rationale"].strip())<=600:
        raise MasterError("master_review_reason_required")
    if data["decision"]=="approve" and (
        data["rights_verified"] is not True or
        data["final_listen_completed"] is not True):
        raise MasterError("master_manual_sound_rights_review_required",409)
    if not isinstance(actor,str) or not 1<=len(actor)<=160:
        raise MasterError("invalid_master_actor")
    current=readiness(db_path,pid,eid)
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise MasterError("audit_integrity_failure",409)
        with transaction(db):
            row=db.execute("SELECT * FROM studio_av_masters WHERE "
                "project_id=? AND episode_id=? AND master_id=?",
                (pid,eid,uid)).fetchone()
            if row is None:raise MasterError("master_not_found",404)
            if row["status"]!="in_review":
                raise MasterError("master_already_reviewed",409)
            if data["decision"]=="approve":
                if not current["ready"] or (
                    row["source_manifest_sha256"]!=current["source_manifest_sha256"]):
                    raise MasterError("master_sources_outdated",409)
                file=_store(db_path)/(uid+".mp4")
                _verify_source(file,row["file_sha256"],row["size_bytes"])
            state={"approve":"approved","reject":"rejected"}[data["decision"]]
            db.execute("UPDATE studio_av_masters SET status=?,"
                "review_reason=?,reviewer=?,reviewed_at=? WHERE master_id=?",
                (state,data["rationale"].strip(),actor,int(time.time()),uid))
            _audit(db,actor,"av.master_"+data["decision"],uid,{
                "project_id":pid,"episode_id":eid,
                "source_sha256":row["source_manifest_sha256"],
                "file_sha256":row["file_sha256"],
                "full_listen_review":data["final_listen_completed"] is True,
                "rights_verified":data["rights_verified"] is True,
                "status":state})
        return {"ok":True,"master_id":uid,"status":state,
            "gpu_action":False}
