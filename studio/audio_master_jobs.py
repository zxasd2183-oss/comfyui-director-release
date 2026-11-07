"""Owner-confirmed durable local A/V mastering jobs. Does not use GPU."""
from __future__ import annotations

import secrets
import sqlite3
import time
from contextlib import closing

from production_core import open_db,transaction,verify_chain,_audit
from audio_master import readiness,mix,MasterError
from picture_cut_jobs import _scope, SHA, PictureJobError

MAX_ATTEMPTS=2


class MasterJobError(ValueError):
    def __init__(self,reason,status=400):
        self.reason,self.status=reason,status
        super().__init__(reason)


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS studio_av_master_jobs(
      job_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,
      episode_id TEXT NOT NULL,manifest_sha256 TEXT NOT NULL,
      requester TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('queued','running','done','failed')),
      attempts INTEGER NOT NULL DEFAULT 0,master_id TEXT,error_code TEXT,
      queued_at INTEGER NOT NULL,started_at INTEGER,finished_at INTEGER,
      FOREIGN KEY(project_id,episode_id) REFERENCES episodes(project_id,episode_id)
    );
    CREATE INDEX IF NOT EXISTS idx_av_master_job_queue
      ON studio_av_master_jobs(status,queued_at);
    """)


def enqueue(db_path,data,actor):
    fields={"project_id","episode_id","source_manifest_sha256",
            "acknowledge_local_cpu"}
    if not isinstance(data,dict) or set(data)!=fields:
        raise MasterJobError("invalid_master_job_request")
    if data["acknowledge_local_cpu"] is not True:
        raise MasterJobError("master_cpu_cost_acknowledgment_required")
    if not isinstance(actor,str) or not 1<=len(actor)<=160:
        raise MasterJobError("invalid_master_job_actor")
    try:pid,eid=_scope(data["project_id"],data["episode_id"])
    except PictureJobError:raise MasterJobError("invalid_master_scope") from None
    digest=data["source_manifest_sha256"]
    if not isinstance(digest,str) or not SHA.fullmatch(digest):
        raise MasterJobError("invalid_master_job_hash")
    ready=readiness(db_path,pid,eid)
    if not ready["ready"] or ready["source_manifest_sha256"]!=digest:
        raise MasterJobError("master_inputs_changed_or_incomplete",409)
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        if not verify_chain(db):
            raise MasterJobError("audit_integrity_failure",409)
        with transaction(db):
            old=db.execute("SELECT job_id,status,master_id FROM studio_av_master_jobs "
                "WHERE project_id=? AND episode_id=? AND manifest_sha256=? "
                "AND status IN ('queued','running','done') "
                "ORDER BY queued_at DESC LIMIT 1",
                (pid,eid,digest)).fetchone()
            if old:
                return {"ok":True,"job_id":old["job_id"],
                    "status":old["status"],"master_id":old["master_id"],
                    "existing":True,"gpu_action":False}
            busy=db.execute("SELECT COUNT(*) FROM studio_av_master_jobs "
                "WHERE status IN ('queued','running')").fetchone()[0]
            if busy>=4:raise MasterJobError("master_cpu_queue_full",409)
            job="AMJOB_"+secrets.token_hex(16)
            db.execute("INSERT INTO studio_av_master_jobs("
                "job_id,project_id,episode_id,manifest_sha256,requester,"
                "status,queued_at) VALUES(?,?,?,?,?,'queued',?)",
                (job,pid,eid,digest,actor,int(time.time())))
            _audit(db,actor,"av.master_job_queued",job,{
                "project_id":pid,"episode_id":eid,
                "source_sha256":digest,"gpu_action":False})
            return {"ok":True,"job_id":job,"status":"queued",
                    "existing":False,"gpu_action":False}


def list_jobs(db_path,project,episode):
    try:pid,eid=_scope(project,episode)
    except PictureJobError:raise MasterJobError("invalid_master_scope") from None
    with closing(open_db(db_path,initialize=False)) as db:
        rows=db.execute("SELECT job_id,manifest_sha256,status,attempts,"
            "master_id,error_code,queued_at,started_at,finished_at "
            "FROM studio_av_master_jobs WHERE project_id=? AND episode_id=? "
            "ORDER BY queued_at DESC,job_id DESC LIMIT 20",
            (pid,eid)).fetchall()
        return {"ok":True,"project_id":pid,"episode_id":eid,
                "jobs":[dict(row) for row in rows],"gpu_action":False}


def recover_running(db_path):
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise MasterJobError("audit_integrity_failure",409)
        with transaction(db):
            rows=db.execute("SELECT job_id,attempts FROM studio_av_master_jobs "
                "WHERE status='running'").fetchall()
            for row in rows:
                retry=row["attempts"]<MAX_ATTEMPTS
                db.execute("UPDATE studio_av_master_jobs SET status=?,"
                    "error_code=?,finished_at=? WHERE job_id=?",
                    ("queued" if retry else "failed",
                     "recovered_after_restart" if retry else "retry_limit_reached",
                     None if retry else int(time.time()),row["job_id"]))
                _audit(db,"studio_media_worker","av.master_job_recovered",
                       row["job_id"],{"requeued":retry,"attempts":row["attempts"]})
        return len(rows)


def process_one(db_path,runner=None):
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise MasterJobError("audit_integrity_failure",409)
        with transaction(db):
            row=db.execute("SELECT job_id,project_id,episode_id,manifest_sha256,"
                "attempts FROM studio_av_master_jobs WHERE status='queued' "
                "ORDER BY queued_at,job_id LIMIT 1").fetchone()
            if row is None:return None
            job=row["job_id"]
            if row["attempts"]>=MAX_ATTEMPTS:
                db.execute("UPDATE studio_av_master_jobs SET status='failed',"
                    "error_code='retry_limit_reached',finished_at=? "
                    "WHERE job_id=?",(int(time.time()),job))
                _audit(db,"studio_media_worker","av.master_job_failed",job,{
                    "reason":"retry_limit_reached"})
                return {"ok":False,"job_id":job,"status":"failed"}
            db.execute("UPDATE studio_av_master_jobs SET status='running',"
                "attempts=attempts+1,started_at=?,error_code=NULL WHERE job_id=?",
                (int(time.time()),job))
            _audit(db,"studio_media_worker","av.master_job_started",job,{
                "attempt":row["attempts"]+1,"gpu_action":False})
    master_id=None;error=None
    try:
        state=readiness(db_path,row["project_id"],row["episode_id"])
        if not state["ready"] or state["source_manifest_sha256"]!=row["manifest_sha256"]:
            raise MasterJobError("master_inputs_changed_or_incomplete",409)
        result=mix(db_path,row["project_id"],row["episode_id"],
                   "studio_media_worker",runner=runner)
        master_id=result["master_id"]
        status="done"
    except (MasterError,MasterJobError) as exc:
        error=exc.reason;status="failed"
    except Exception:
        error="master_cpu_worker_failed";status="failed"
    with closing(open_db(db_path)) as db:
        if not verify_chain(db):
            raise MasterJobError("audit_integrity_failure",409)
        with transaction(db):
            db.execute("UPDATE studio_av_master_jobs SET status=?,"
                "master_id=?,error_code=?,finished_at=? WHERE job_id=?",
                (status,master_id,error,int(time.time()),job))
            _audit(db,"studio_media_worker","av.master_job_"+status,job,{
                "master_id":master_id,"reason":error,"gpu_action":False})
    return {"ok":status=="done","job_id":job,"status":status,
            "master_id":master_id,"error_code":error,"gpu_action":False}


def media_worker_loop(db_path,should_continue):
    """One CPU lane; prevents independent picture and audio FFmpeg contention."""
    from picture_cut_jobs import recover_running as recover_picture
    from picture_cut_jobs import process_one as process_picture
    from release_jobs import recover_running as recover_release
    from release_jobs import process_one as process_release
    try:
        recover_picture(db_path)
        recover_running(db_path)
        recover_release(db_path)
    except Exception:
        return
    while should_continue():
        try:
            processed=process_picture(db_path)
            if processed is None:
                processed=process_one(db_path)
            if processed is None:
                processed=process_release(db_path)
        except Exception:
            processed=None
        if not should_continue():break
        time.sleep(2 if processed is not None else 4)
