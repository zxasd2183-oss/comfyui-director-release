"""In-memory acknowledgement and status for ChatGPT→Studio visual file transfers.

The MCP call returns a short receipt immediately; an isolated daemon worker
downloads the authorized short-lived file and writes to Studio. The temporary
signed URL is never retained in a job record or written to disk. Completed
job receipts are short-lived. Studio remains the durable source of truth.
No GPU or power APIs are imported.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time

from hub_file_sync import SyncError, validate_file_ref, sync_chatgpt_visual

_JOB_ID=re.compile(r"^SYNC_[0-9a-f]{24}$")
_IDENT=re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,47}$")
_KINDS=frozenset({"character","scene","storyboard"})


class VisualSyncJobs:
    def __init__(self, transfer=sync_chatgpt_visual, *, clock=time.time,
                 ttl_seconds=3600, max_active=4, max_history=128):
        self.transfer=transfer
        self.clock=clock
        self.ttl_seconds=ttl_seconds
        self.max_active=max_active
        self.max_history=max_history
        self.lock=threading.Lock()
        self.jobs={}
        self.by_file={}

    def _prune(self, now):
        for job_id,entry in list(self.jobs.items()):
            if entry["status"] in ("succeeded","failed") and (
                    now-entry["finished_at"]>self.ttl_seconds):
                self.jobs.pop(job_id,None)
                self.by_file.pop(entry["fingerprint"],None)
        completed=sorted((j for j in self.jobs.values()
                         if j["status"] in ("succeeded","failed")),
                         key=lambda j:j["finished_at"],reverse=True)
        for entry in completed[self.max_history:]:
            self.jobs.pop(entry["job_id"],None)
            self.by_file.pop(entry["fingerprint"],None)

    def _public(self,entry,*,reused=False):
        response={
            "ok":True,"job_id":entry["job_id"],"status":entry["status"],
            "project_id":entry["project_id"],"episode_id":entry["episode_id"],
            "kind":entry["kind"],"subject_id":entry["subject_id"],
            "created_at":entry["created_at"]
        }
        if reused:
            response["existing_job"]=True
        if entry["status"] in ("succeeded","failed"):
            response["finished_at"]=entry["finished_at"]
            response["result"]=dict(entry["result"])
        return response

    def submit(self,project_id,episode_id,kind,subject_id,file):
        if not all(isinstance(item,str) and _IDENT.fullmatch(item)
                   for item in (project_id,episode_id,subject_id)):
            return {"ok":False,"reason":"invalid_studio_scope"}
        if kind not in _KINDS:
            return {"ok":False,"reason":"invalid_visual_kind"}
        try:
            # Validate before starting a worker; NEVER persist the URL.
            _url,source_token=validate_file_ref(file)
        except SyncError as exc:
            return {"ok":False,"reason":exc.reason}
        fingerprint=hashlib.sha256(
            "\x00".join((project_id,episode_id,kind,subject_id,source_token))
            .encode("utf-8")).hexdigest()
        with self.lock:
            now=int(self.clock())
            self._prune(now)
            previous_id=self.by_file.get(fingerprint)
            if previous_id and previous_id in self.jobs:
                return self._public(self.jobs[previous_id],reused=True)
            active=sum(j["status"] in ("queued","running")
                       for j in self.jobs.values())
            if active>=self.max_active:
                return {"ok":False,"reason":"studio_sync_queue_full"}
            import secrets
            job_id="SYNC_"+secrets.token_hex(12)
            entry={
                "job_id":job_id,"project_id":project_id,
                "episode_id":episode_id,"kind":kind,"subject_id":subject_id,
                "fingerprint":fingerprint,"status":"queued",
                "created_at":now,"finished_at":None,"result":None
            }
            self.jobs[job_id]=entry
            self.by_file[fingerprint]=job_id
            # File data lives in worker args only; never job records.
            worker=threading.Thread(
                target=self._run,args=(job_id,project_id,episode_id,
                                       kind,subject_id,file),
                name="director-visual-sync",daemon=True)
            worker.start()
            return self._public(entry)

    def _run(self,job_id,pid,eid,kind,subject,file):
        with self.lock:
            if job_id not in self.jobs:
                return
            self.jobs[job_id]["status"]="running"
        try:
            result=self.transfer(pid,eid,kind,subject,file)
            if not isinstance(result,dict) or result.get("ok") is not True:
                reason=result.get("reason") if isinstance(result,dict) else None
                if reason not in {
                    "invalid_chatgpt_file_reference","invalid_chatgpt_file_url",
                    "invalid_chatgpt_file_id","untrusted_chatgpt_file_host",
                    "chatgpt_download_dns_unavailable",
                    "chatgpt_download_tls_error",
                    "chatgpt_download_network_error",
                    "chatgpt_download_http_error",
                    "chatgpt_download_redirect_blocked",
                    "chatgpt_image_size_unsupported",
                    "image_mime_mismatch","unsupported_image_format",
                    "studio_visual_ingest_http_error",
                    "studio_visual_ingest_unavailable",
                    "studio_visual_sync_unavailable",
                    "brain_link_not_configured","invalid_filename"
                }:
                    reason="visual_sync_failed"
                result={"ok":False,"reason":reason}
            else:
                # Only include verified non-sensitive receipt fields.
                result={
                    "ok":True,"visual_id":result.get("visual_id"),
                    "version":result.get("version"),
                    "unchanged":result.get("unchanged",False),
                    "gpu_action":False
                }
        except Exception:
            result={"ok":False,"reason":"visual_sync_worker_failed"}
        with self.lock:
            if job_id in self.jobs:
                entry=self.jobs[job_id]
                entry["result"]=result
                entry["finished_at"]=int(self.clock())
                entry["status"]="succeeded" if result["ok"] else "failed"

    def status(self,job_id):
        if not isinstance(job_id,str) or not _JOB_ID.fullmatch(job_id):
            return {"ok":False,"reason":"invalid_sync_job_id"}
        with self.lock:
            self._prune(int(self.clock()))
            entry=self.jobs.get(job_id)
            return self._public(entry) if entry else {
                "ok":False,"reason":"sync_job_not_found"
            }

    def recent(self,project_id,episode_id):
        if not all(isinstance(item,str) and _IDENT.fullmatch(item)
                   for item in (project_id,episode_id)):
            return {"ok":False,"reason":"invalid_studio_scope"}
        with self.lock:
            self._prune(int(self.clock()))
            entries=sorted((j for j in self.jobs.values()
                            if j["project_id"]==project_id and
                               j["episode_id"]==episode_id),
                           key=lambda j:j["created_at"],reverse=True)[:10]
            return {"ok":True,"project_id":project_id,"episode_id":episode_id,
                    "jobs":[self._public(j) for j in entries],
                    "volatile":True}


JOBS=VisualSyncJobs()
