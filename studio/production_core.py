"""Director Studio V0.9 production ledger: projects, episodes, shots, audiovisual
assets, provenance, continuity findings, scoped director exceptions, and
tamper-evident event history. No cloud, GPU, login, or media access.

All mutations are LOCAL CLI operations using a dedicated unprivileged service
identity; HTTP only exposes a bounded read-only dashboard until full OIDC.
"""
from __future__ import annotations

import hashlib
import json
import math
from contextlib import contextmanager
import re
import sqlite3
import time
from pathlib import Path

IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,47}$")
SHOT_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
ATTR = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,3}$")
KINDS = frozenset({"character_visual", "character_voice", "costume", "location",
                   "prop", "dialogue", "soundscape", "sound_effect", "music",
                   "video_take", "audio_take", "timeline"})
RIGHTS_REQUIRED = frozenset({"character_voice", "dialogue", "music", "sound_effect", "audio_take"})
MAX_EVIDENCE_TEXT = 500


class ProductionError(ValueError):
    pass


def _ident(value):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ProductionError("invalid_identifier")
    return value


def _shot_ident(value):
    if not isinstance(value, str) or not SHOT_IDENT.fullmatch(value):
        raise ProductionError("invalid_shot_identifier")
    return value


def _text(value, limit=160):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit or
            any(ord(c) < 32 for c in value)):
        raise ProductionError("invalid_text")
    return value.strip()


def _sha(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ProductionError("invalid_sha256")
    return value


def _attr(value):
    if not isinstance(value, str) or not ATTR.fullmatch(value):
        raise ProductionError("invalid_continuity_attribute")
    return value


def open_db(path, *, initialize=True):
    p = Path(path)
    if p.is_symlink() or not p.parent.is_dir():
        raise ProductionError("invalid_database_path")
    if not initialize and not p.is_file():
        raise ProductionError("database_not_initialized")
    connection = sqlite3.connect(str(p) if initialize else
        "file:" + p.resolve().as_posix() + "?mode=ro",
        uri=not initialize, isolation_level=None, timeout=6)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=6000")
    if not initialize:
        return connection
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS projects (
      project_id TEXT PRIMARY KEY, title TEXT NOT NULL,
      created_at INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS episodes (
      project_id TEXT NOT NULL, episode_id TEXT NOT NULL, title TEXT NOT NULL,
      ordinal INTEGER NOT NULL, stage TEXT NOT NULL DEFAULT 'planning',
      PRIMARY KEY(project_id,episode_id),
      UNIQUE(project_id,ordinal),
      FOREIGN KEY(project_id) REFERENCES projects(project_id));
    CREATE TABLE IF NOT EXISTS production_shots (
      project_id TEXT NOT NULL, episode_id TEXT NOT NULL, shot_id TEXT NOT NULL,
      ordinal INTEGER NOT NULL, duration_ms INTEGER NOT NULL,
      stage TEXT NOT NULL DEFAULT 'planned',
      PRIMARY KEY(project_id,episode_id,shot_id),
      UNIQUE(project_id,episode_id,ordinal),
      FOREIGN KEY(project_id,episode_id)
        REFERENCES episodes(project_id,episode_id));
    CREATE TABLE IF NOT EXISTS episode_plan_imports (
      project_id TEXT NOT NULL, episode_id TEXT NOT NULL,
      source_sha256 TEXT NOT NULL, shot_count INTEGER NOT NULL,
      imported_at INTEGER NOT NULL,
      PRIMARY KEY(project_id,episode_id),
      FOREIGN KEY(project_id,episode_id) REFERENCES episodes(project_id,episode_id));
    CREATE TABLE IF NOT EXISTS assets (
      asset_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
      kind TEXT NOT NULL, subject_id TEXT NOT NULL,
      version INTEGER NOT NULL, sha256 TEXT NOT NULL,
      rights_ref TEXT NOT NULL, created_at INTEGER NOT NULL,
      UNIQUE(project_id,kind,subject_id,version),
      FOREIGN KEY(project_id) REFERENCES projects(project_id));
    CREATE TABLE IF NOT EXISTS shot_assets (
      project_id TEXT NOT NULL, episode_id TEXT NOT NULL, shot_id TEXT NOT NULL,
      asset_id TEXT NOT NULL, purpose TEXT NOT NULL,
      PRIMARY KEY(project_id,episode_id,shot_id,asset_id,purpose),
      FOREIGN KEY(project_id,episode_id,shot_id)
        REFERENCES production_shots(project_id,episode_id,shot_id),
      FOREIGN KEY(asset_id) REFERENCES assets(asset_id));
    CREATE TABLE IF NOT EXISTS findings (
      finding_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
      episode_id TEXT NOT NULL, shot_id TEXT NOT NULL,
      attribute TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
      detail TEXT NOT NULL, created_at INTEGER NOT NULL,
      FOREIGN KEY(project_id,episode_id,shot_id)
        REFERENCES production_shots(project_id,episode_id,shot_id));
    CREATE TABLE IF NOT EXISTS exceptions (
      exception_id TEXT PRIMARY KEY, finding_id TEXT NOT NULL UNIQUE,
      attribute TEXT NOT NULL,
      start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
      permitted_change TEXT NOT NULL, rationale TEXT NOT NULL,
      evidence_sha256 TEXT NOT NULL,
      bound_asset_id TEXT, status TEXT NOT NULL DEFAULT 'draft',
      reviewer TEXT, approved_at INTEGER,
      revision INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY(finding_id) REFERENCES findings(finding_id),
      FOREIGN KEY(bound_asset_id) REFERENCES assets(asset_id));
    CREATE TABLE IF NOT EXISTS audit_chain (
      id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL,
      actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,
      detail TEXT NOT NULL, prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL);
    """ )
    return connection


@contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def _audit(db, actor, action, target, data):
    """Append-only hash chain. External signed snapshots needed for admin tamper resistance."""
    actor = _ident(actor)
    old = db.execute("SELECT event_hash FROM audit_chain ORDER BY id DESC LIMIT 1").fetchone()
    previous = old["event_hash"] if old else "0" * 64
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    at = time.time_ns()
    payload = json.dumps([at,actor,action,target,canonical,previous],
                         ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    db.execute("INSERT INTO audit_chain(at,actor,action,target,detail,prev_hash,event_hash)"
               " VALUES(?,?,?,?,?,?,?)",
               (at, actor, action, target, canonical, previous, digest))
    return digest


def verify_chain(db):
    previous = "0" * 64
    for e in db.execute("SELECT at,actor,action,target,detail,prev_hash,event_hash "
                        "FROM audit_chain ORDER BY id"):
        payload = json.dumps([e["at"],e["actor"],e["action"],e["target"],e["detail"],
                              previous], ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        if e["prev_hash"] != previous or e["event_hash"] != digest:
            return False
        previous = digest
    return True


def create_project(db, project_id, title, *, actor="studio_operator"):
    pid, title = _ident(project_id), _text(title)
    with transaction(db):
        db.execute("INSERT INTO projects(project_id,title,created_at) VALUES(?,?,?)",
                   (pid, title, int(time.time())))
        _audit(db, actor, "project.created", pid, {"title": title})
    return pid


def create_episode(db, project_id, episode_id, title, ordinal, *, actor="studio_operator"):
    pid, eid, title = _ident(project_id), _ident(episode_id), _text(title)
    if type(ordinal) is not int or not 1 <= ordinal <= 1000:
        raise ProductionError("invalid_episode_order")
    with transaction(db):
        db.execute("INSERT INTO episodes(project_id,episode_id,title,ordinal) "
                   "VALUES(?,?,?,?)", (pid,eid,title,ordinal))
        _audit(db,actor,"episode.created",pid+"/"+eid,{"title":title,"ordinal":ordinal})


def create_shot(db, project_id, episode_id, shot_id, ordinal, duration_ms,
                *, actor="studio_operator"):
    pid, eid, sid = _ident(project_id), _ident(episode_id), _shot_ident(shot_id)
    if (type(ordinal) is not int or not 1 <= ordinal <= 10000 or
            type(duration_ms) is not int or not 1 <= duration_ms <= 120000):
        raise ProductionError("invalid_shot_timing")
    with transaction(db):
        db.execute("INSERT INTO production_shots(project_id,episode_id,shot_id,ordinal,duration_ms)"
                   " VALUES(?,?,?,?,?)", (pid,eid,sid,ordinal,duration_ms))
        _audit(db,actor,"shot.created",pid+"/"+eid+"/"+sid,
               {"ordinal":ordinal,"duration_ms":duration_ms})


def import_video_plan(db, project_id, episode_id, file, *, actor="studio_operator"):
    """Import an entire V0.7 plan as shot metadata only (no prompts/graphs)."""
    pid,eid = _ident(project_id),_ident(episode_id)
    source = Path(file)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 4_000_000:
        raise ProductionError("invalid_video_plan_file")
    raw = source.read_bytes()
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ProductionError("invalid_video_plan_json") from None
    jobs = obj.get("jobs") if isinstance(obj,dict) and obj.get("schema")==1 else None
    if not isinstance(jobs,list) or not 1 <= len(jobs) <= 500:
        raise ProductionError("invalid_video_plan_schema")
    imported, seen = [], set()
    for i,job in enumerate(jobs,1):
        if not isinstance(job,dict):
            raise ProductionError("invalid_video_plan_shot")
        sid=_shot_ident(job.get("shot_id"))
        seconds=job.get("seconds")
        if (sid in seen or type(seconds) not in (int,float) or
                not math.isfinite(seconds) or not 0 < seconds <= 30):
            raise ProductionError("invalid_video_plan_shot")
        seen.add(sid)
        imported.append((pid,eid,sid,i,max(1,round(seconds*1000))))
    digest=hashlib.sha256(raw).hexdigest()
    with transaction(db):
        row=db.execute("SELECT source_sha256,shot_count FROM episode_plan_imports "
                       "WHERE project_id=? AND episode_id=?", (pid,eid)).fetchone()
        if row:
            if row["source_sha256"] != digest:
                raise ProductionError("episode_plan_changed_use_new_reviewed_version")
            return {"ok":True,"unchanged":True,"shots":row["shot_count"],
                    "source_sha256":digest}
        if db.execute("SELECT COUNT(*) FROM production_shots WHERE project_id=? "
                      "AND episode_id=?", (pid,eid)).fetchone()[0]:
            raise ProductionError("episode_already_has_manual_shots")
        db.executemany("INSERT INTO production_shots "
                       "(project_id,episode_id,shot_id,ordinal,duration_ms)"
                       " VALUES(?,?,?,?,?)", imported)
        db.execute("INSERT INTO episode_plan_imports "
                   "(project_id,episode_id,source_sha256,shot_count,imported_at) "
                   "VALUES(?,?,?,?,?)", (pid,eid,digest,len(imported),int(time.time())))
        _audit(db,actor,"episode.plan_imported",pid+"/"+eid,
               {"shots":len(imported),"source_sha256":digest})
    return {"ok":True,"unchanged":False,"shots":len(imported),"source_sha256":digest}


def add_asset(db, asset_id, project_id, kind, subject_id, version, sha256,
              rights_ref, *, actor="studio_operator"):
    aid, pid, subject = _ident(asset_id), _ident(project_id), _ident(subject_id)
    if kind not in KINDS:
        raise ProductionError("invalid_asset_kind")
    if type(version) is not int or not 1 <= version <= 100000:
        raise ProductionError("invalid_asset_version")
    digest = _sha(sha256)
    if rights_ref:
        rights_ref = _text(rights_ref, MAX_EVIDENCE_TEXT)
    elif kind in RIGHTS_REQUIRED:
        raise ProductionError("audio_rights_or_consent_reference_required")
    else:
        rights_ref = "owner_declared"
    with transaction(db):
        old = db.execute(
            "SELECT asset_id FROM assets WHERE project_id=? AND kind=? "
            "AND subject_id=? AND version>=?",
            (pid,kind,subject,version)).fetchone()
        if old:
            raise ProductionError("asset_version_must_increase")
        db.execute("INSERT INTO assets(asset_id,project_id,kind,subject_id,version,"
                   "sha256,rights_ref,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (aid,pid,kind,subject,version,digest,rights_ref,int(time.time())))
        # New approved voice/visual identity versions may invalidate historical
        # exceptions; make them stale, never silently grant new allowances.
        db.execute("""
          UPDATE exceptions SET status='stale',revision=revision+1
          WHERE status='approved' AND bound_asset_id IN (
            SELECT asset_id FROM assets WHERE project_id=? AND kind=? AND
            subject_id=? AND version<?)
        """, (pid,kind,subject,version))
        _audit(db,actor,"asset.registered",aid,
               {"project_id":pid,"kind":kind,"subject_id":subject,
                "version":version,"sha256":digest,"rights_ref":rights_ref})


def attach_asset(db, project_id, episode_id, shot_id, asset_id, purpose,
                 *, actor="studio_operator"):
    pid,eid,aid = map(_ident, (project_id,episode_id,asset_id))
    sid = _shot_ident(shot_id)
    purpose = _text(purpose, 60)
    with transaction(db):
        asset = db.execute("SELECT project_id FROM assets WHERE asset_id=?", (aid,)).fetchone()
        if not asset or asset["project_id"] != pid:
            raise ProductionError("asset_not_in_project")
        db.execute("INSERT INTO shot_assets(project_id,episode_id,shot_id,asset_id,purpose)"
                   " VALUES(?,?,?,?,?)", (pid,eid,sid,aid,purpose))
        _audit(db,actor,"shot.asset_linked",pid+"/"+eid+"/"+sid,
               {"asset_id":aid,"purpose":purpose})


def create_finding(db, finding_id, project_id, episode_id, shot_id,
                   attribute, evidence_sha256, detail, *, actor="studio_operator"):
    fid,pid,eid = map(_ident,(finding_id,project_id,episode_id))
    sid = _shot_ident(shot_id)
    attribute, evidence = _attr(attribute), _sha(evidence_sha256)
    detail = _text(detail,MAX_EVIDENCE_TEXT)
    with transaction(db):
        db.execute("INSERT INTO findings(finding_id,project_id,episode_id,shot_id,attribute,"
                   "evidence_sha256,detail,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (fid,pid,eid,sid,attribute,evidence,detail,int(time.time())))
        _audit(db,actor,"continuity.finding_created",fid,
               {"attribute":attribute,"evidence_sha256":evidence})


def draft_exception(db, exception_id, finding_id, start_ms, end_ms,
                    permitted_change, rationale, evidence_sha256,
                    bound_asset_id=None, *, actor="studio_operator"):
    xid, fid = _ident(exception_id), _ident(finding_id)
    if type(start_ms) is not int or type(end_ms) is not int or start_ms < 0 or end_ms <= start_ms:
        raise ProductionError("invalid_exception_time_range")
    permitted_change = _text(permitted_change,MAX_EVIDENCE_TEXT)
    rationale = _text(rationale,MAX_EVIDENCE_TEXT)
    evidence = _sha(evidence_sha256)
    aid = _ident(bound_asset_id) if bound_asset_id else None
    with transaction(db):
        finding = db.execute("SELECT * FROM findings WHERE finding_id=?", (fid,)).fetchone()
        if finding is None:
            raise ProductionError("finding_not_found")
        shot = db.execute(
            "SELECT duration_ms FROM production_shots WHERE project_id=? AND "
            "episode_id=? AND shot_id=?",
            (finding["project_id"],finding["episode_id"],finding["shot_id"])).fetchone()
        if shot is None or end_ms > shot["duration_ms"]:
            raise ProductionError("exception_outside_shot")
        if aid:
            asset = db.execute("SELECT project_id FROM assets WHERE asset_id=?", (aid,)).fetchone()
            if not asset or asset["project_id"] != finding["project_id"]:
                raise ProductionError("exception_asset_wrong_project")
            linked = db.execute(
                "SELECT 1 FROM shot_assets WHERE project_id=? AND episode_id=? "
                "AND shot_id=? AND asset_id=?",
                (finding["project_id"], finding["episode_id"], finding["shot_id"], aid)
            ).fetchone()
            if linked is None:
                raise ProductionError("exception_asset_not_linked_to_shot")
        db.execute("INSERT INTO exceptions(exception_id,finding_id,attribute,start_ms,end_ms,"
                   "permitted_change,rationale,evidence_sha256,bound_asset_id)"
                   " VALUES(?,?,?,?,?,?,?,?,?)",
                   (xid,fid,finding["attribute"],start_ms,end_ms,
                    permitted_change,rationale,evidence,aid))
        _audit(db,actor,"exception.drafted",xid,
               {"finding_id":fid,"start_ms":start_ms,"end_ms":end_ms,
                "attribute":finding["attribute"],"evidence_sha256":evidence})


def decide_exception(db, exception_id, decision, expected_revision,
                     *, actor, confirmation):
    """Only local SSH CLI calls this; never expose on V0.9 HTTP."""
    xid, actor = _ident(exception_id), _ident(actor)
    if decision not in ("approve", "revoke") or confirmation != "I_HAVE_REVIEWED_EVIDENCE":
        raise ProductionError("explicit_review_confirmation_required")
    if type(expected_revision) is not int or expected_revision < 1:
        raise ProductionError("invalid_revision")
    with transaction(db):
        row = db.execute("SELECT status,revision,bound_asset_id FROM exceptions WHERE exception_id=?",
                         (xid,)).fetchone()
        if row is None:
            raise ProductionError("exception_not_found")
        if row["revision"] != expected_revision:
            raise ProductionError("stale_exception_revision")
        if decision == "approve" and row["status"] != "draft":
            raise ProductionError("only_draft_can_be_approved")
        if decision == "approve":
            if not row["bound_asset_id"]:
                raise ProductionError("exception_version_binding_required")
            version = db.execute("""
                SELECT original.version, MAX(latest.version) AS newest
                FROM assets AS original
                JOIN assets AS latest
                  ON original.project_id=latest.project_id
                 AND original.kind=latest.kind
                 AND original.subject_id=latest.subject_id
                WHERE original.asset_id=?
            """, (row["bound_asset_id"],)).fetchone()
            if version is None or version["newest"] is None or version["version"] != version["newest"]:
                raise ProductionError("stale_bound_asset_version")
        if decision == "revoke" and row["status"] != "approved":
            raise ProductionError("only_approved_can_be_revoked")
        target = "approved" if decision == "approve" else "revoked"
        db.execute("UPDATE exceptions SET status=?,reviewer=?,approved_at=?,"
                   "revision=revision+1 WHERE exception_id=?",
                   (target,actor,int(time.time()) if target=="approved" else None,xid))
        _audit(db,actor,"exception."+target,xid,
               {"old_state":row["status"],"status":target,
                "previous_revision":row["revision"],"review_confirmation":True})
    return {"exception_id":xid,"status":target,"revision":expected_revision+1,
            "gpu_action":False}


def dashboard(db):
    """Bounded read-only projection, no full prompts, paths, audio bytes or keys."""
    projects = db.execute(
        "SELECT project_id,title,revision FROM projects ORDER BY created_at,project_id LIMIT 20"
    ).fetchall()
    episodes = db.execute(
        "SELECT project_id,episode_id,title,ordinal,stage FROM episodes "
        "ORDER BY project_id,ordinal LIMIT 100").fetchall()
    counts = {name:db.execute("SELECT COUNT(*) FROM "+name).fetchone()[0]
              for name in ("projects","episodes","production_shots","assets","findings","exceptions")}
    kinds = db.execute("SELECT kind,COUNT(*) AS count FROM assets "
                       "GROUP BY kind ORDER BY kind").fetchall()
    exceptions = db.execute("SELECT status,COUNT(*) AS count FROM exceptions "
                            "GROUP BY status").fetchall()
    return {"version":"0.9.0","mode":"read_only_production_summary",
            "counts":counts,
            "projects":[dict(r) for r in projects],
            "episodes":[dict(r) for r in episodes],
            "asset_kinds":{r["kind"]:r["count"] for r in kinds},
            "exception_status":{r["status"]:r["count"] for r in exceptions},
            "audio_asset_count":sum(r["count"] for r in kinds if r["kind"] in
                RIGHTS_REQUIRED | {"character_voice","soundscape"}),
            "audit_chain_verified":verify_chain(db),
            "controls":{"gpu_power":False,"gpu_dispatch":False,
                        "public_asset_mutations":False}}


def episode_detail(db, project_id, episode_id):
    """Private, bounded projection. Never return prompts, file paths or rights data."""
    pid,eid = _ident(project_id),_ident(episode_id)
    row=db.execute(
        "SELECT e.project_id,e.episode_id,e.title,e.ordinal,e.stage,p.title AS project_title "
        "FROM episodes e JOIN projects p ON p.project_id=e.project_id "
        "WHERE e.project_id=? AND e.episode_id=?",
        (pid,eid)).fetchone()
    if row is None:
        raise ProductionError("episode_not_found")
    shots=db.execute(
        "SELECT shot_id,ordinal,duration_ms,stage FROM production_shots "
        "WHERE project_id=? AND episode_id=? ORDER BY ordinal LIMIT 501",
        (pid,eid)).fetchall()
    assets=db.execute(
        "SELECT DISTINCT a.asset_id,a.kind,a.subject_id,a.version "
        "FROM shot_assets sa JOIN assets a ON a.asset_id=sa.asset_id "
        "WHERE sa.project_id=? AND sa.episode_id=? "
        "ORDER BY a.kind,a.subject_id,a.version LIMIT 151",
        (pid,eid)).fetchall()
    findings=db.execute(
        "SELECT COUNT(*) FROM findings WHERE project_id=? AND episode_id=?",
        (pid,eid)).fetchone()[0]
    exceptions=db.execute(
        "SELECT x.status,COUNT(*) AS count FROM exceptions x "
        "JOIN findings f ON f.finding_id=x.finding_id "
        "WHERE f.project_id=? AND f.episode_id=? GROUP BY x.status",
        (pid,eid)).fetchall()
    return {
        "ok":True,"mode":"read_only_episode_detail",
        "episode":dict(row),
        "shot_count":db.execute(
            "SELECT COUNT(*) FROM production_shots WHERE project_id=? AND episode_id=?",
            (pid,eid)).fetchone()[0],
        "shots":[dict(r) for r in shots[:500]],
        "shots_truncated":len(shots)>500,
        "assets":[dict(r) for r in assets[:150]],
        "assets_truncated":len(assets)>150,
        "finding_count":findings,
        "exceptions_by_status":{r["status"]:r["count"] for r in exceptions},
    }


def episode_detail_from_path(path,project_id,episode_id):
    from contextlib import closing
    with closing(open_db(path,initialize=False)) as db:
        return episode_detail(db,project_id,episode_id)


def dashboard_from_path(path):
    from contextlib import closing
    with closing(open_db(path,initialize=False)) as db:
        return dashboard(db)
