"""Approved video-only episode picture cuts, separate from final sound master.

One immutable cut requires a current human-approved real MP4 for EVERY shot.
Assembly uses the VPS's local ffprobe/ffmpeg only, never ComfyUI/GPU/network.
A picture cut is not dubbed, mixed, mastered or final-release approved.
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

from production_core import (_ident, _audit, open_db, transaction,
                             verify_chain, ProductionError)
from production_workflows import get_video_handoff_package, WorkflowError
from video_results import _safe_root, _file_digest, VideoResultError

CUT_ID=re.compile(r"^CUT_[0-9a-f]{32}$")


class PictureCutError(ValueError):
    def __init__(self,reason,status=400):
        self.reason,self.status=reason,status
        super().__init__(reason)


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS studio_picture_cuts(
      cut_id TEXT PRIMARY KEY,
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
    CREATE INDEX IF NOT EXISTS idx_picture_cuts_episode
      ON studio_picture_cuts(project_id,episode_id,created_at);
    """)


def _ids(project,episode):
    try:return _ident(project),_ident(episode)
    except ProductionError:
        raise PictureCutError("invalid_picture_cut_scope") from None


def get_readiness(db_path,project_id,episode_id):
    pid,eid=_ids(project_id,episode_id)
    with closing(open_db(db_path,initialize=False)) as db:
        if db.execute("SELECT 1 FROM episodes WHERE project_id=? AND "
                      "episode_id=?",(pid,eid)).fetchone() is None:
            raise PictureCutError("episode_not_found",404)
        rows=db.execute("SELECT shot_id,ordinal,duration_ms FROM production_shots "
            "WHERE project_id=? AND episode_id=? ORDER BY ordinal,shot_id "
            "LIMIT 501",(pid,eid)).fetchall()
        if len(rows)>500:raise PictureCutError("too_many_episode_shots",409)
        shots=[]
        blocked=[]
        for row in rows:
            sid=row["shot_id"]
            reason=[]
            try:
                package=get_video_handoff_package(db_path,pid,eid,sid)
                video=package["package"]["video_plan"]
                other=[x for x in package["package"]["blockers"]
                       if x!="video_render_executor_not_connected"]
                if video["status"]!="in_review":
                    reason.append("video_plan_not_in_review")
                reason+=other
            except WorkflowError as exc:
                package=None
                reason.append(exc.reason)
            current_sha=package["package_sha256"] if package else None
            current_rev=package["package"]["video_plan"]["revision"] if package else None
            choices=db.execute("SELECT take_id,plan_revision,package_sha256,"
                "sha256,size_bytes,width,height,fps,duration_seconds,codec,"
                "reviewed_at FROM studio_video_takes WHERE "
                "project_id=? AND episode_id=? AND shot_id=? AND status='approved' "
                "ORDER BY reviewed_at DESC,created_at DESC,take_id DESC LIMIT 80",
                (pid,eid,sid)).fetchall()
            matching=next((x for x in choices
                if x["plan_revision"]==current_rev and
                   x["package_sha256"]==current_sha),None)
            if matching is None:
                reason.append("current_approved_video_take_missing")
            if reason:
                blocked.append({"shot_id":sid,"ordinal":row["ordinal"],
                                "reasons":sorted(set(reason))})
            shots.append({"shot_id":sid,"ordinal":row["ordinal"],
                "duration_ms":row["duration_ms"],
                "take_id":matching["take_id"] if matching else None,
                "sha256":matching["sha256"] if matching else None,
                "size_bytes":matching["size_bytes"] if matching else None,
                "source_package_sha256":current_sha,
                "source_plan_revision":current_rev})
        record={"schema":"director_studio_approved_picture_cut_v1",
            "project_id":pid,"episode_id":eid,
            "shot_count":len(rows),"total_duration_ms":sum(
                r["duration_ms"] for r in rows),"shots":shots}
        digest=hashlib.sha256(json.dumps(record,sort_keys=True,
            ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
        return {"ok":True,"project_id":pid,"episode_id":eid,
            "shot_count":len(rows),"approved_count":len(rows)-len(blocked),
            "total_duration_ms":record["total_duration_ms"],
            "ready":bool(rows) and not blocked,
            "blocked":blocked,"source_manifest_sha256":digest,
            "source_manifest":record,
            "render_or_gpu_required":False}


def _signature(path,run):
    cmd=["/usr/bin/ffprobe","-v","error",
         "-show_entries","format=duration:stream=codec_type,codec_name,width,height,"
         "pix_fmt,avg_frame_rate,sample_rate,channels",
         "-of","json",str(path)]
    try:
        result=run(cmd,capture_output=True,timeout=20,check=False)
        if result.returncode!=0 or len(result.stdout)>65536:
            raise ValueError
        meta=json.loads(result.stdout)
        streams=meta["streams"]
        if not isinstance(streams,list) or not streams:
            raise ValueError
        fields=("codec_type","codec_name","width","height","pix_fmt",
                "avg_frame_rate","sample_rate","channels")
        signature=tuple(tuple(row.get(f) for f in fields) for row in streams)
        if sum(1 for row in signature if row[0]=="video")!=1:
            raise ValueError
        duration=float(meta["format"]["duration"])
        if not 0<duration<3600:
            raise ValueError
        return signature,duration
    except (OSError,ValueError,KeyError,TypeError,IndexError,
            subprocess.TimeoutExpired):
        raise PictureCutError("picture_cut_ffprobe_failed",422) from None


def _private_dir(db_path,create=False):
    root=_safe_root(db_path,create=create)/"picture_cuts"
    if root.is_symlink():raise PictureCutError("unsafe_picture_storage",503)
    if create:root.mkdir(mode=0o700,exist_ok=True)
    if not root.is_dir() or root.stat().st_mode&0o077:
        raise PictureCutError("unsafe_picture_storage",503)
    return root


def assemble(db_path,project_id,episode_id,actor,runner=None):
    """Run only under the local service operator identity, not a public GET.

    Revalidates source hashes and current approvals before any FFmpeg action.
    """
    if not isinstance(actor,str) or not 1<=len(actor)<=160:
        raise PictureCutError("invalid_picture_cut_actor")
    run=subprocess.run if runner is None else runner
    readiness=get_readiness(db_path,project_id,episode_id)
    if not readiness["ready"]:
        raise PictureCutError("approved_picture_cut_incomplete",409)
    pid,eid=readiness["project_id"],readiness["episode_id"]
    source=readiness["source_manifest"]
    root=_safe_root(db_path)
    paths=[]
    for entry in source["shots"]:
        target=root/(entry["take_id"]+".mp4")
        if target.is_symlink() or not target.is_file() or (
            target.stat().st_size!=entry["size_bytes"] or
            _file_digest(target)!=entry["sha256"]):
            raise PictureCutError("picture_cut_source_media_changed",409)
        paths.append(target)
    signatures=[_signature(p,run) for p in paths]
    first=signatures[0][0]
    if any(sig!=first for sig,duration in signatures[1:]):
        raise PictureCutError("picture_cut_streams_incompatible",409)
    expected=source["total_duration_ms"]/1000
    if abs(sum(t[1] for t in signatures)-expected)>max(.5,len(paths)*.25):
        raise PictureCutError("picture_cut_total_duration_changed",409)

    destdir=_private_dir(db_path,create=True)
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        if not verify_chain(db):
            raise PictureCutError("audit_integrity_failure",409)
        existing=db.execute("SELECT * FROM studio_picture_cuts WHERE "
            "project_id=? AND episode_id=? AND source_manifest_sha256=? "
            "ORDER BY created_at DESC LIMIT 1",
            (pid,eid,readiness["source_manifest_sha256"])).fetchone()
        if existing:
            file=destdir/(existing["cut_id"]+".mp4")
            if file.is_file() and not file.is_symlink() and (
                file.stat().st_size==existing["size_bytes"] and
                _file_digest(file)==existing["file_sha256"]):
                return {"ok":True,"already_assembled":True,
                    "cut_id":existing["cut_id"],"status":existing["status"],
                    "gpu_action":False}
            raise PictureCutError("picture_cut_existing_storage_mismatch",503)
    expected_bytes=sum(x["size_bytes"] for x in source["shots"])
    if shutil.disk_usage(destdir).free<expected_bytes+100_000_000:
        raise PictureCutError("picture_cut_storage_space_insufficient",507)
    cut_id="CUT_"+secrets.token_hex(16)
    destination=destdir/(cut_id+".mp4")
    concat=None
    staging=None
    published=False
    try:
        with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=str(destdir),
            prefix=".picture-cut-",suffix=".ffconcat",delete=False) as f:
            concat=f.name
            f.write("ffconcat version 1.0\n")
            for path in paths:
                escaped=str(path).replace("'","'\\''")
                f.write("file '"+escaped+"'\n")
        fd,staging=tempfile.mkstemp(prefix=".picture-output-",
                                   suffix=".mp4",dir=str(destdir))
        os.close(fd)
        try:
            result=run(["/usr/bin/ffmpeg","-nostdin","-hide_banner",
                "-loglevel","error","-f","concat","-safe","0","-i",concat,
                "-map","0","-c","copy","-movflags","+faststart",
                "-y",staging],capture_output=True,check=False,timeout=3600)
        except (OSError,subprocess.TimeoutExpired):
            raise PictureCutError("picture_cut_ffmpeg_unavailable",503) from None
        if result.returncode!=0 or not Path(staging).is_file() or (
            Path(staging).stat().st_size<128):
            raise PictureCutError("picture_cut_ffmpeg_failed",422)
        result_sig,result_length=_signature(staging,run)
        if result_sig!=first or abs(result_length-expected)>max(.5,len(paths)*.25):
            raise PictureCutError("picture_cut_output_validation_failed",422)
        # Audit a fresh, exact approved inventory before publishing. Never
        # register a completed cut whose source changed during FFmpeg.
        latest=get_readiness(db_path,pid,eid)
        if not latest["ready"] or (
            latest["source_manifest_sha256"]!=readiness["source_manifest_sha256"]):
            raise PictureCutError("picture_cut_source_revision_changed",409)
        digest=_file_digest(Path(staging))
        bytes_written=Path(staging).stat().st_size
        os.link(staging,destination)
        published=True
        with closing(open_db(db_path)) as db:
            if not verify_chain(db):
                raise PictureCutError("audit_integrity_failure",409)
            with transaction(db):
                db.execute("INSERT INTO studio_picture_cuts("
                    "cut_id,project_id,episode_id,source_manifest_sha256,"
                    "source_manifest_json,file_sha256,size_bytes,duration_seconds,"
                    "status,created_at) VALUES(?,?,?,?,?,?,?,?,'in_review',?)",
                    (cut_id,pid,eid,readiness["source_manifest_sha256"],
                     json.dumps(source,sort_keys=True,ensure_ascii=False),
                     digest,bytes_written,result_length,int(time.time())))
                _audit(db,actor,"picture_cut.created",cut_id,{
                    "project_id":pid,"episode_id":eid,
                    "shot_count":source["shot_count"],
                    "source_sha256":readiness["source_manifest_sha256"],
                    "file_sha256":digest,"status":"in_review"})
        return {"ok":True,"cut_id":cut_id,
            "file_sha256":digest,"size_bytes":bytes_written,
            "status":"in_review","gpu_action":False,
            "sound_mastered":False}
    except BaseException:
        if published:destination.unlink(missing_ok=True)
        raise
    finally:
        if staging:Path(staging).unlink(missing_ok=True)
        if concat:Path(concat).unlink(missing_ok=True)


def list_cuts(db_path,project,episode):
    pid,eid=_ids(project,episode)
    with closing(open_db(db_path,initialize=False)) as db:
        if db.execute("SELECT 1 FROM episodes WHERE project_id=? AND "
                      "episode_id=?",(pid,eid)).fetchone() is None:
            raise PictureCutError("episode_not_found",404)
        rows=db.execute("SELECT cut_id,project_id,episode_id,"
            "source_manifest_sha256,file_sha256,size_bytes,duration_seconds,"
            "status,review_reason,reviewer,created_at,reviewed_at "
            "FROM studio_picture_cuts WHERE project_id=? AND episode_id=? "
            "ORDER BY created_at DESC LIMIT 30",(pid,eid)).fetchall()
        current=get_readiness(db_path,pid,eid)["source_manifest_sha256"]
        return {"ok":True,"project_id":pid,"episode_id":eid,
            "picture_cuts":[dict(row,source_current=(
                row["source_manifest_sha256"]==current)) for row in rows],
            "final_audio_mixed":False,"gpu_action":False}


def get_cut_file(db_path,project,episode,cut_id):
    pid,eid=_ids(project,episode)
    if not isinstance(cut_id,str) or not CUT_ID.fullmatch(cut_id):
        raise PictureCutError("invalid_picture_cut_id")
    with closing(open_db(db_path,initialize=False)) as db:
        row=db.execute("SELECT size_bytes FROM studio_picture_cuts WHERE "
            "project_id=? AND episode_id=? AND cut_id=?",
            (pid,eid,cut_id)).fetchone()
        if row is None:raise PictureCutError("picture_cut_not_found",404)
        path=_private_dir(db_path)/(cut_id+".mp4")
        if path.is_symlink() or not path.is_file() or (
            path.stat().st_size!=row["size_bytes"]):
            raise PictureCutError("picture_cut_storage_mismatch",503)
        return path,row["size_bytes"]


def review_cut(db_path,fields,actor):
    if not isinstance(fields,dict) or set(fields)!={
        "project_id","episode_id","cut_id","decision","rationale"}:
        raise PictureCutError("invalid_picture_cut_review")
    pid,eid=_ids(fields["project_id"],fields["episode_id"])
    uid=fields["cut_id"]
    action=fields["decision"]
    reason=fields["rationale"]
    if not isinstance(uid,str) or not CUT_ID.fullmatch(uid):
        raise PictureCutError("invalid_picture_cut_id")
    if action not in ("approve","reject") or not isinstance(reason,str) or (
        not 8<=len(reason.strip())<=600):
        raise PictureCutError("picture_cut_review_reason_required")
    if not isinstance(actor,str) or not 1<=len(actor)<=160:
        raise PictureCutError("invalid_picture_cut_actor")
    ready=get_readiness(db_path,pid,eid)
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise PictureCutError("audit_integrity_failure",409)
        with transaction(db):
            row=db.execute("SELECT * FROM studio_picture_cuts WHERE "
                "project_id=? AND episode_id=? AND cut_id=?",
                (pid,eid,uid)).fetchone()
            if row is None:raise PictureCutError("picture_cut_not_found",404)
            if row["status"]!="in_review":
                raise PictureCutError("picture_cut_already_reviewed",409)
            if action=="approve":
                if not ready["ready"] or (
                    row["source_manifest_sha256"]!=ready["source_manifest_sha256"]):
                    raise PictureCutError("picture_cut_source_revision_changed",409)
                path=_private_dir(db_path)/(uid+".mp4")
                if path.is_symlink() or not path.is_file() or (
                    path.stat().st_size!=row["size_bytes"] or
                    _file_digest(path)!=row["file_sha256"]):
                    raise PictureCutError("picture_cut_storage_mismatch",503)
            status={"approve":"approved","reject":"rejected"}[action]
            now=int(time.time())
            db.execute("UPDATE studio_picture_cuts SET status=?,review_reason=?,"
                "reviewer=?,reviewed_at=? WHERE cut_id=?",
                (status,reason.strip(),actor,now,uid))
            _audit(db,actor,"picture_cut."+action,uid,{
                "project_id":pid,"episode_id":eid,
                "source_sha256":row["source_manifest_sha256"],
                "media_sha256":row["file_sha256"],"status":status})
        return {"ok":True,"cut_id":uid,"status":status,
            "final_audio_mixed":False,"gpu_action":False}
