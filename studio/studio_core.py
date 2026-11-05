"""Director Studio V0.8: local-only audited production supervision ledger.

No GPU start/stop, ComfyUI enqueue/interrupt or secret storage.
All operator actions here are scheduling/review decisions, never hardware actions.
"""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path

SHOT_ID = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
COMMANDS = frozenset({
    "pause_dispatch", "resume_dispatch", "hold_shot", "release_shot",
    "request_rework", "approve_shot", "add_note",
})
SHOT_COMMANDS = frozenset({"hold_shot", "release_shot", "request_rework", "approve_shot", "add_note"})
MAX_SHOTS = 500

class StudioError(ValueError):
    pass


def connect(path):
    target = Path(path)
    if target.is_symlink() or not target.parent.is_dir():
        raise StudioError("studio_database_path_unavailable")
    db = sqlite3.connect(str(target), isolation_level=None, timeout=8)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=8000")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS studio_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS shots (
        id TEXT PRIMARY KEY, position INTEGER NOT NULL, seconds REAL NOT NULL,
        stage TEXT NOT NULL DEFAULT 'planned',
        held INTEGER NOT NULL DEFAULT 0, review TEXT NOT NULL DEFAULT 'pending',
        revision INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS studio_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL,
        actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT,
        detail TEXT NOT NULL
    );
    INSERT OR IGNORE INTO studio_meta(key,value) VALUES ('dispatch_paused','1');
    """)
    return db


def _event(db, action, target, detail, actor="ssh_operator"):
    db.execute("INSERT INTO studio_events(at,actor,action,target,detail) VALUES (?,?,?,?,?)",
               (int(time.time()), actor, action, target, detail))


def import_plan(db, path):
    """Import ONLY redacted shot IDs, duration and order from V0.7 plan.json."""
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 4_000_000:
        raise StudioError("invalid_plan_file")
    raw = source.read_bytes()
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise StudioError("invalid_plan_json") from None
    jobs = data.get("jobs") if isinstance(data, dict) and data.get("schema") == 1 else None
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= MAX_SHOTS:
        raise StudioError("invalid_plan_schema")
    entries, seen = [], set()
    for i, j in enumerate(jobs):
        if not isinstance(j, dict):
            raise StudioError("invalid_shot")
        sid, seconds = j.get("shot_id"), j.get("seconds")
        if (not isinstance(sid, str) or not SHOT_ID.fullmatch(sid) or sid in seen or
                type(seconds) not in (float, int) or not 0 < seconds <= 30):
            raise StudioError("invalid_shot")
        seen.add(sid)
        entries.append((sid, i + 1, seconds))
    digest = hashlib.sha256(raw).hexdigest()
    db.execute("BEGIN IMMEDIATE")
    try:
        old = db.execute("SELECT value FROM studio_meta WHERE key='plan_sha256'").fetchone()
        if old:
            if old["value"] != digest:
                raise StudioError("plan_already_imported_use_new_database")
            db.execute("COMMIT")
            return {"ok": True, "shot_count": len(entries), "unchanged": True}
        if db.execute("SELECT COUNT(*) FROM shots").fetchone()[0]:
            raise StudioError("nonempty_studio_requires_new_database")
        db.executemany("INSERT INTO shots(id,position,seconds) VALUES (?,?,?)", entries)
        db.execute("INSERT INTO studio_meta(key,value) VALUES ('plan_sha256',?)", (digest,))
        _event(db, "plan_imported", None, "shot_count:" + str(len(entries)))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return {"ok": True, "shot_count": len(entries), "unchanged": False}


def snapshot(db):
    rows = db.execute("SELECT id,position,seconds,stage,held,review,revision FROM shots ORDER BY position").fetchall()
    meta = db.execute("SELECT value FROM studio_meta WHERE key='dispatch_paused'").fetchone()
    events = db.execute(
        "SELECT id,at,actor,action,target,detail FROM studio_events ORDER BY id DESC LIMIT 40"
    ).fetchall()
    return {
        "schema": 1, "mode": "operator_ledger_only",
        "dispatch_paused": meta is None or meta["value"] == "1",
        "shots": [
            {"id": r["id"], "position": r["position"], "seconds": r["seconds"],
             "stage": r["stage"], "held": bool(r["held"]), "review": r["review"],
             "revision": r["revision"]} for r in rows
        ],
        "events": [dict(r) for r in events],
        "capabilities": {
            "live_gpu_monitoring": True,
            "pause_future_dispatch": True,
            "review_and_rework_ledger": True,
            "interrupt_running_comfyui": False,
            "cancel_submitted_comfyui": False,
            "direct_gpu_power": False,
        },
    }


def decide(db, action, *, shot_id=None, revision=None, reason=""):
    """Atomic operator command with revision check, audit and fail-closed rules."""
    if action not in COMMANDS or type(reason) is not str or len(reason) > 500 or "\x00" in reason:
        raise StudioError("invalid_command")
    if action in ("request_rework", "add_note") and not reason.strip():
        raise StudioError("reason_required")
    if action in SHOT_COMMANDS:
        if (not isinstance(shot_id, str) or not SHOT_ID.fullmatch(shot_id) or
                type(revision) is not int or revision < 0):
            raise StudioError("invalid_shot_target")
    elif shot_id is not None or revision is not None:
        raise StudioError("unexpected_shot_target")
    db.execute("BEGIN IMMEDIATE")
    try:
        if action not in SHOT_COMMANDS:
            value = "1" if action == "pause_dispatch" else "0"
            db.execute("UPDATE studio_meta SET value=? WHERE key='dispatch_paused'", (value,))
        else:
            row = db.execute(
                "SELECT stage,held,review,revision FROM shots WHERE id=?", (shot_id,)
            ).fetchone()
            if row is None:
                raise StudioError("shot_not_found")
            if row["revision"] != revision:
                raise StudioError("stale_shot_revision")
            if action == "hold_shot":
                db.execute("UPDATE shots SET held=1,revision=revision+1 WHERE id=?", (shot_id,))
            elif action == "release_shot":
                db.execute("UPDATE shots SET held=0,revision=revision+1 WHERE id=?", (shot_id,))
            elif action == "request_rework":
                db.execute("UPDATE shots SET review='rework',held=1,revision=revision+1 WHERE id=?", (shot_id,))
            elif action == "approve_shot":
                if row["stage"] != "review":
                    raise StudioError("review_artifact_not_verified")
                db.execute("UPDATE shots SET review='approved',revision=revision+1 WHERE id=?", (shot_id,))
            elif action == "add_note":
                db.execute("UPDATE shots SET revision=revision+1 WHERE id=?", (shot_id,))
        _event(db, action, shot_id, reason[:500])
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return {"ok": True, "action": action, "target": shot_id,
            "effect": "operator_ledger_only", "executed_on_gpu": False}


def dispatch_eligible(db):
    """Scheduling advisory only; future GPU worker MUST independently honor it."""
    snap = snapshot(db)
    if snap["dispatch_paused"]:
        return []
    return [s["id"] for s in snap["shots"]
            if s["stage"] == "planned" and not s["held"] and s["review"] == "pending"]
