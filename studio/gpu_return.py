"""Owner-issued episode-scoped GPU video return tokens; hashes only in SQLite."""
from __future__ import annotations
import hashlib
import hmac
import re
import secrets
import time
from contextlib import closing

from production_core import _audit, _ident, open_db, transaction, verify_chain, ProductionError

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,120}$")
TTL = 48 * 3600


class ReturnError(ValueError):
    def __init__(self, reason, status=400):
        self.reason = reason
        self.status = status
        super().__init__(reason)


def prepare_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS studio_gpu_return_tokens (
      token_hash TEXT PRIMARY KEY,
      token_id TEXT NOT NULL UNIQUE,
      project_id TEXT NOT NULL,
      episode_id TEXT NOT NULL,
      issuer TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      expires_at INTEGER NOT NULL,
      revoked_at INTEGER,
      FOREIGN KEY(project_id,episode_id) REFERENCES episodes(project_id,episode_id)
    )""")


def issue(db_path, project_id, episode_id, actor):
    try:
        pid, eid, owner = _ident(project_id), _ident(episode_id), _ident(actor)
    except ProductionError:
        raise ReturnError("invalid_gpu_return_scope") from None
    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    token_id = secrets.token_hex(12)
    now = int(time.time())
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        if not verify_chain(db):
            raise ReturnError("audit_integrity_failure", 409)
        with transaction(db):
            row = db.execute("SELECT 1 FROM episodes WHERE project_id=? AND episode_id=?",
                             (pid,eid)).fetchone()
            if not row:
                raise ReturnError("episode_not_found",404)
            db.execute("UPDATE studio_gpu_return_tokens SET revoked_at=? WHERE "
                       "project_id=? AND episode_id=? AND revoked_at IS NULL",
                       (now,pid,eid))
            db.execute("INSERT INTO studio_gpu_return_tokens "
                       "(token_hash,token_id,project_id,episode_id,issuer,created_at,expires_at) "
                       "VALUES(?,?,?,?,?,?,?)",
                       (digest,token_id,pid,eid,owner,now,now+TTL))
            _audit(db,owner,"gpu_return.token_issued",pid+"/"+eid,
                   {"token_id":token_id,"expires_at":now+TTL})
    return {"ok":True,"token":token,"token_id":token_id,
            "project_id":pid,"episode_id":eid,"expires_at":now+TTL,
            "permissions":["video_import_in_review_only"],"gpu_action":False}


def authenticate(db_path, header):
    if not isinstance(header,str) or not header.startswith("Bearer "):
        raise ReturnError("gpu_return_token_required",401)
    token = header[7:]
    if not TOKEN_PATTERN.fullmatch(token):
        raise ReturnError("gpu_return_token_invalid",401)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    with closing(open_db(db_path,initialize=False)) as db:
        row=db.execute("SELECT * FROM studio_gpu_return_tokens WHERE token_hash=?",
                       (digest,)).fetchone()
    if (row is None or row["revoked_at"] is not None
            or row["expires_at"]<=int(time.time())
            or not hmac.compare_digest(row["token_hash"],digest)):
        raise ReturnError("gpu_return_token_expired_or_invalid",401)
    return {"actor":"gpureturn_"+row["token_id"],
            "project_id":row["project_id"],"episode_id":row["episode_id"]}


def check_scope(credential, values):
    if (values.get("project_id") != credential["project_id"] or
            values.get("episode_id") != credential["episode_id"]):
        raise ReturnError("gpu_return_scope_mismatch",403)
