"""Explicit owner-requested VPS CPU picture-cut queue, never GPU tasks.

Worker is started only by the real Studio server entrypoint. Authenticated
requests enqueue immutable approved manifests; a single local worker performs
FFmpeg independently of HTTP request timeouts. Jobs are persistent/audited.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
import time
from contextlib import closing

from production_core import open_db, verify_chain, transaction, _audit, _ident, ProductionError
from picture_cuts import get_readiness, assemble, PictureCutError

ID=re.compile(r"^PCJOB_[0-9a-f]{32}$")
SHA=re.compile(r"^[0-9a-f]{64}$")
MAX_ATTEMPTS=2


class PictureJobError(ValueError):
    def __init__(self,reason,status=400):
        self.reason,self.status=reason,status
        super().__init__(reason)


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS studio_picture_cut_jobs(
      job_id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,episode_id TEXT NOT NULL,
      manifest_sha256 TEXT NOT NULL,requester TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('queued','running','done','failed')),
      attempts INTEGER NOT NULL DEFAULT 0,
      cut_id TEXT,error_code TEXT,
      queued_at INTEGER NOT NULL,started_at INTEGER,finished_at INTEGER,
      FOREIGN KEY(project_id,episode_id) REFERENCES episodes(project_id,episode_id)
    );
    CREATE INDEX IF NOT EXISTS idx_picture_jobs_status
      ON studio_picture_cut_jobs(status,queued_at);
    """)


def _scope(project,episode):
    try:return _ident(project),_ident(episode)
    except ProductionError:
        raise PictureJobError("invalid_picture_cut_job_scope") from None


def enqueue(db_path,data,actor):
    required={"project_id","episode_id","source_manifest_sha256",
              "acknowledge_local_cpu"}
    if not isinstance(data,dict) or set(data)!=required:
        raise PictureJobError("invalid_picture_cut_job_request")
    if data["acknowledge_local_cpu"] is not True:
        raise PictureJobError("local_cpu_cost_acknowledgment_required")
    if not isinstance(actor,str) or not 1<=len(actor)<=160:
        raise PictureJobError("invalid_picture_cut_job_actor")
    pid,eid=_scope(data["project_id"],data["episode_id"])
    digest=data["source_manifest_sha256"]
    if not isinstance(digest,str) or not SHA.fullmatch(digest):
        raise PictureJobError("invalid_picture_cut_job_hash")
    ready=get_readiness(db_path,pid,eid)
    if not ready["ready"] or ready["source_manifest_sha256"]!=digest:
        raise PictureJobError("picture_cut_source_changed_or_incomplete",409)
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise PictureJobError("audit_integrity_failure",409)
        with transaction(db):
            active=db.execute("SELECT job_id,status,cut_id FROM studio_picture_cut_jobs "
                "WHERE project_id=? AND episode_id=? AND manifest_sha256=? "
                "AND status IN ('queued','running','done') "
                "ORDER BY queued_at DESC LIMIT 1",(pid,eid,digest)).fetchone()
            if active:
                return {"ok":True,"job_id":active["job_id"],
                    "status":active["status"],"cut_id":active["cut_id"],
                    "existing":True,"gpu_action":False}
            if db.execute("SELECT COUNT(*) FROM studio_picture_cut_jobs "
                "WHERE status IN ('queued','running')").fetchone()[0]>=4:
                raise PictureJobError("picture_cut_cpu_queue_full",409)
            job="PCJOB_"+secrets.token_hex(16)
            db.execute("INSERT INTO studio_picture_cut_jobs("
                "job_id,project_id,episode_id,manifest_sha256,requester,"
                "status,queued_at) VALUES(?,?,?,?,?,'queued',?)",
                (job,pid,eid,digest,actor,int(time.time())))
            _audit(db,actor,"picture_cut.job_queued",job,{
                "project_id":pid,"episode_id":eid,"source_sha256":digest,
                "gpu_action":False})
        return {"ok":True,"job_id":job,"status":"queued",
            "existing":False,"gpu_action":False}


def list_jobs(db_path,project,episode):
    pid,eid=_scope(project,episode)
    with closing(open_db(db_path,initialize=False)) as db:
        if db.execute("SELECT 1 FROM episodes WHERE project_id=? "
                      "AND episode_id=?",(pid,eid)).fetchone() is None:
            raise PictureJobError("episode_not_found",404)
        rows=db.execute("SELECT job_id,manifest_sha256,status,attempts,"
            "cut_id,error_code,queued_at,started_at,finished_at "
            "FROM studio_picture_cut_jobs WHERE project_id=? AND episode_id=? "
            "ORDER BY queued_at DESC,job_id DESC LIMIT 20",
            (pid,eid)).fetchall()
        return {"ok":True,"project_id":pid,"episode_id":eid,
                "jobs":[dict(row) for row in rows],"gpu_action":False}


def recover_running(db_path):
    """Reclaim work after a service restart, bounded to two total attempts."""
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise PictureJobError("audit_integrity_failure",409)
        with transaction(db):
            rows=db.execute("SELECT job_id,attempts FROM studio_picture_cut_jobs "
                "WHERE status='running'").fetchall()
            for row in rows:
                retry=row["attempts"]<MAX_ATTEMPTS
                db.execute("UPDATE studio_picture_cut_jobs SET status=?,"
                    "error_code=?,finished_at=? WHERE job_id=?",
                    ("queued" if retry else "failed",
                     "recovered_after_restart" if retry else "retry_limit_reached",
                     None if retry else int(time.time()),row["job_id"]))
                _audit(db,"studio_picture_worker","picture_cut.job_recovered",
                       row["job_id"],{"requeued":retry,"attempts":row["attempts"]})
    return len(rows)


def process_one(db_path,runner=None):
    """Claim at most one job; local FFmpeg may take minutes, never in HTTP."""
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise PictureJobError("audit_integrity_failure",409)
        with transaction(db):
            row=db.execute("SELECT job_id,project_id,episode_id,"
                "manifest_sha256,attempts FROM studio_picture_cut_jobs "
                "WHERE status='queued' ORDER BY queued_at,job_id LIMIT 1").fetchone()
            if row is None:return None
            job=row["job_id"]
            if row["attempts"]>=MAX_ATTEMPTS:
                db.execute("UPDATE studio_picture_cut_jobs SET status='failed',"
                    "error_code='retry_limit_reached',finished_at=? "
                    "WHERE job_id=?",(int(time.time()),job))
                _audit(db,"studio_picture_worker","picture_cut.job_failed",job,{
                    "reason":"retry_limit_reached"})
                return {"ok":False,"job_id":job,"status":"failed"}
            db.execute("UPDATE studio_picture_cut_jobs SET status='running',"
                "attempts=attempts+1,started_at=?,error_code=NULL "
                "WHERE job_id=?",(int(time.time()),job))
            _audit(db,"studio_picture_worker","picture_cut.job_started",job,{
                "attempt":row["attempts"]+1,"gpu_action":False})
    cut_id=None
    error=None
    try:
        ready=get_readiness(db_path,row["project_id"],row["episode_id"])
        if not ready["ready"] or (
            ready["source_manifest_sha256"]!=row["manifest_sha256"]):
            raise PictureJobError("picture_cut_source_changed_or_incomplete",409)
        result=assemble(db_path,row["project_id"],row["episode_id"],
                        "studio_picture_worker",runner=runner)
        cut_id=result["cut_id"]
        state="done"
    except (PictureCutError,PictureJobError) as exc:
        error=exc.reason
        state="failed"
    except (OSError,sqlite3.Error,ValueError):
        error="picture_cut_worker_failed"
        state="failed"
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise PictureJobError("audit_integrity_failure",409)
        with transaction(db):
            db.execute("UPDATE studio_picture_cut_jobs SET status=?,cut_id=?,"
                "error_code=?,finished_at=? WHERE job_id=?",
                (state,cut_id,error,int(time.time()),job))
            _audit(db,"studio_picture_worker","picture_cut.job_"+state,job,{
                "cut_id":cut_id,"reason":error,"gpu_action":False})
    return {"ok":state=="done","job_id":job,"status":state,
            "cut_id":cut_id,"error_code":error,"gpu_action":False}


def worker_loop(db_path,should_continue):
    # Startup on the same single-instance Studio service; never from HTTP.
    try:recover_running(db_path)
    except (PictureJobError,OSError,sqlite3.Error):
        return
    while should_continue():
        try:
            processed=process_one(db_path)
        except (PictureJobError,OSError,sqlite3.Error):
            processed=None
        if not should_continue():break
        time.sleep(2 if processed else 4)
