"""Private persistent web sessions for the pinned Microsoft Studio owner.

The database contains ONLY SHA-256 digests of 256-bit random session handles,
a pseudonymous owner digest, CSRF nonces and bounded expiry timestamps. No
Microsoft access/refresh/ID tokens, OAuth codes, email, or raw session cookies.
It is stored in systemd's private StateDirectory across Studio code restarts.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path


class SessionStoreError(ValueError):
    pass


class PersistentSessions:
    def __init__(self, path, *, max_sessions=20):
        self.path=Path(path)
        self.max_sessions=max_sessions
        self._prepare()

    @staticmethod
    def _digest(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _ensure_private(self):
        folder=self.path.parent
        if (folder.is_symlink() or not folder.is_dir()
                or folder.stat().st_uid != os.geteuid()
                or stat.S_IMODE(folder.stat().st_mode)&0o077):
            raise SessionStoreError("session_directory_unsafe")
        if self.path.is_symlink():
            raise SessionStoreError("session_database_unsafe")
        if not self.path.exists():
            try:
                fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            except FileExistsError:
                if self.path.is_symlink():
                    raise SessionStoreError("session_database_unsafe")
            else:
                os.close(fd)
        details=self.path.stat()
        if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.geteuid()
                or stat.S_IMODE(details.st_mode)&0o077):
            raise SessionStoreError("session_database_unsafe")

    def _connect(self):
        self._ensure_private()
        conn=sqlite3.connect(str(self.path),timeout=6,isolation_level=None)
        conn.row_factory=sqlite3.Row
        conn.execute("PRAGMA busy_timeout=6000")
        return conn

    def _prepare(self):
        with closing(self._connect()) as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS studio_owner_sessions (
              sid_digest TEXT PRIMARY KEY,
              owner_digest TEXT NOT NULL,
              csrf TEXT NOT NULL,
              created_at REAL NOT NULL,
              expires REAL NOT NULL,
              last_seen REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_studio_owner_expiration
              ON studio_owner_sessions(expires);
            """)

    def save(self, sid, owner_sub, csrf, now, expires, idle_seconds):
        handle=self._digest(sid)
        owner=self._digest(owner_sub)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("DELETE FROM studio_owner_sessions "
                           "WHERE expires<=? OR last_seen+?<=? "
                           "OR owner_digest<>?",
                           (now,idle_seconds,now,owner))
                number=db.execute("SELECT COUNT(*) FROM studio_owner_sessions").fetchone()[0]
                if number>=self.max_sessions:
                    raise SessionStoreError("too_many_sessions")
                db.execute("INSERT INTO studio_owner_sessions "
                           "(sid_digest,owner_digest,csrf,created_at,expires,last_seen) "
                           "VALUES(?,?,?,?,?,?)",
                           (handle,owner,csrf,now,expires,now))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def lookup(self,sid,owner_sub,now,idle_seconds):
        with closing(self._connect()) as db:
            data=db.execute(
                "SELECT owner_digest,csrf,expires,last_seen FROM studio_owner_sessions "
                "WHERE sid_digest=?",(self._digest(sid),)).fetchone()
            if data is None:return None
            if (data["owner_digest"]!=self._digest(owner_sub) or
                data["expires"]<=now or data["last_seen"]+idle_seconds<=now):
                db.execute("DELETE FROM studio_owner_sessions WHERE sid_digest=?",
                           (self._digest(sid),))
                return None
            # Limit SSD writes from long-lived SSE connections while retaining
            # 14-day inactivity expiry. Every refresh extends idle time.
            if now-data["last_seen"]>=60:
                db.execute("UPDATE studio_owner_sessions SET last_seen=? "
                           "WHERE sid_digest=?",(now,self._digest(sid)))
            return {"sub":owner_sub,"csrf":data["csrf"]}

    def remove(self,sid):
        with closing(self._connect()) as db:
            db.execute("DELETE FROM studio_owner_sessions WHERE sid_digest=?",
                       (self._digest(sid),))

    def revoke_all(self,owner_sub):
        with closing(self._connect()) as db:
            db.execute("DELETE FROM studio_owner_sessions WHERE owner_digest=?",
                       (self._digest(owner_sub),))
