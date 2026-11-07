"""Private reviewed subtitle mux jobs; never publish or power GPU."""
from __future__ import annotations

import secrets
import sqlite3
import time
from contextlib import closing

from production_core import open_db,transaction,verify_chain,_audit
from release_candidates import readiness,mux,ReleaseError
from picture_cut_jobs import _scope, SHA, PictureJobError

MAX_ATTEMPTS=2


class ReleaseJobError(ValueError):
    def __init__(self,reason,status=400):
        self.reason,self.status=reason,status
        super().__init__(reason)


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS studio_release_jobs(
      job_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,
      episode_id TEXT NOT NULL,manifest_sha256 TEXT NOT NULL,
      requester TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('queued','running','done','failed')),
      attempts INTEGER NOT NULL DEFAULT 0,release_id TEXT,error_code TEXT,
      queued_at INTEGER NOT NULL,started_at INTEGER,finished_at INTEGER,
      FOREIGN KEY(project_id,episode_id) REFERENCES episodes(project_id,episode_id)
    );
    CREATE INDEX IF NOT EXISTS idx_release_job_queue
      ON studio_release_jobs(status,queued_at);
    """)


def enqueue(db_path,data,actor):
    fields={"project_id","episode_id","source_manifest_sha256",
            "acknowledge_local_cpu"}
    if not isinstance(data,dict) or set(data)!=fields:
        raise ReleaseJobError("invalid_release_job_request")
    if data["acknowledge_local_cpu"] is not True:
        raise ReleaseJobError("release_cpu_cost_acknowledgment_required")
    if not isinstance(actor,str) or not 1<=len(actor)<=160:
        raise ReleaseJobError("invalid_release_job_actor")
    try:pid,eid=_scope(data["project_id"],data["episode_id"])
    except PictureJobError:raise ReleaseJobError("invalid_release_scope") from None
    digest=data["source_manifest_sha256"]
    if not isinstance(digest,str) or not SHA.fullmatch(digest):
        raise ReleaseJobError("invalid_release_job_hash")
    ready=readiness(db_path,pid,eid)
    if not ready["ready"] or ready["source_manifest_sha256"]!=digest:
        raise ReleaseJobError("release_inputs_changed_or_incomplete",409)
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        if not verify_chain(db):
            raise ReleaseJobError("audit_integrity_failure",409)
        with transaction(db):
            old=db.execute("SELECT job_id,status,release_id FROM studio_release_jobs "
                "WHERE project_id=? AND episode_id=? AND manifest_sha256=? "
                "AND status IN ('queued','running','done') "
                "ORDER BY queued_at DESC LIMIT 1",
                (pid,eid,digest)).fetchone()
            if old:
                return {"ok":True,"job_id":old["job_id"],
                    "status":old["status"],"release_id":old["release_id"],
                    "existing":True,"gpu_action":False}
            busy=db.execute("SELECT COUNT(*) FROM studio_release_jobs "
                "WHERE status IN ('queued','running')").fetchone()[0]
            if busy>=4:raise ReleaseJobError("release_cpu_queue_full",409)
            job="RLJOB_"+secrets.token_hex(16)
            db.execute("INSERT INTO studio_release_jobs("
                "job_id,project_id,episode_id,manifest_sha256,requester,"
                "status,queued_at) VALUES(?,?,?,?,?,'queued',?)",
                (job,pid,eid,digest,actor,int(time.time())))
            _audit(db,actor,"release.job_queued",job,{
                "project_id":pid,"episode_id":eid,
                "source_sha256":digest,"gpu_action":False})
            return {"ok":True,"job_id":job,"status":"queued",
                    "existing":False,"gpu_action":False}


def list_jobs(db_path,project,episode):
    try:pid,eid=_scope(project,episode)
    except PictureJobError:raise ReleaseJobError("invalid_release_scope") from None
    with closing(open_db(db_path,initialize=False)) as db:
        rows=db.execute("SELECT job_id,manifest_sha256,status,attempts,"
            "release_id,error_code,queued_at,started_at,finished_at "
            "FROM studio_release_jobs WHERE project_id=? AND episode_id=? "
            "ORDER BY queued_at DESC,job_id DESC LIMIT 20",
            (pid,eid)).fetchall()
        return {"ok":True,"project_id":pid,"episode_id":eid,
                "jobs":[dict(row) for row in rows],"gpu_action":False}


def recover_running(db_path):
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise ReleaseJobError("audit_integrity_failure",409)
        with transaction(db):
            rows=db.execute("SELECT job_id,attempts FROM studio_release_jobs "
                "WHERE status='running'").fetchall()
            for row in rows:
                retry=row["attempts"]<MAX_ATTEMPTS
                db.execute("UPDATE studio_release_jobs SET status=?,"
                    "error_code=?,finished_at=? WHERE job_id=?",
                    ("queued" if retry else "failed",
                     "recovered_after_restart" if retry else "retry_limit_reached",
                     None if retry else int(time.time()),row["job_id"]))
                _audit(db,"studio_media_worker","release.job_recovered",
                       row["job_id"],{"requeued":retry,"attempts":row["attempts"]})
        return len(rows)


def process_one(db_path,runner=None):
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise ReleaseJobError("audit_integrity_failure",409)
        with transaction(db):
            row=db.execute("SELECT job_id,project_id,episode_id,manifest_sha256,"
                "attempts FROM studio_release_jobs WHERE status='queued' "
                "ORDER BY queued_at,job_id LIMIT 1").fetchone()
            if row is None:return None
            job=row["job_id"]
            if row["attempts"]>=MAX_ATTEMPTS:
                db.execute("UPDATE studio_release_jobs SET status='failed',"
                    "error_code='retry_limit_reached',finished_at=? "
                    "WHERE job_id=?",(int(time.time()),job))
                _audit(db,"studio_media_worker","release.job_failed",job,{
                    "reason":"retry_limit_reached"})
                return {"ok":False,"job_id":job,"status":"failed"}
            db.execute("UPDATE studio_release_jobs SET status='running',"
                "attempts=attempts+1,started_at=?,error_code=NULL WHERE job_id=?",
                (int(time.time()),job))
            _audit(db,"studio_media_worker","release.job_started",job,{
                "attempt":row["attempts"]+1,"gpu_action":False})
    release_id=None;error=None
    try:
        state=readiness(db_path,row["project_id"],row["episode_id"])
        if not state["ready"] or state["source_manifest_sha256"]!=row["manifest_sha256"]:
            raise ReleaseJobError("release_inputs_changed_or_incomplete",409)
        result=mux(db_path,row["project_id"],row["episode_id"],
                   "studio_media_worker",runner=runner)
        release_id=result["release_id"]
        status="done"
    except (ReleaseError,ReleaseJobError) as exc:
        error=exc.reason;status="failed"
    except Exception:
        error="release_cpu_worker_failed";status="failed"
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise ReleaseJobError("audit_integrity_failure",409)
        with transaction(db):
            db.execute("UPDATE studio_release_jobs SET status=?,"
                "release_id=?,error_code=?,finished_at=? WHERE job_id=?",
                (status,release_id,error,int(time.time()),job))
            _audit(db,"studio_media_worker","release.job_"+status,job,{
                "release_id":release_id,"reason":error,"gpu_action":False})
    return {"ok":status=="done","job_id":job,"status":status,
            "release_id":release_id,"error_code":error,"gpu_action":False}


