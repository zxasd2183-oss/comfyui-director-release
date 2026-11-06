"""Director Studio: reusable project scene catalog, NOT a page-only prototype.

Each scene has a stable identity and versioned set/light/camera/continuity
rules. Episode-local scene images are referenced, never copied or promoted
without Microsoft-owner review. No GPU/network/power effects.
"""
from __future__ import annotations

import hashlib
import json
import time
from contextlib import closing

from production_core import open_db, transaction, _audit, _ident, ProductionError
from character_library import CharacterError, _check_audit

SCENE_TYPES=frozenset(("interior","exterior","transition","abstract"))
REFERENCE_TYPES=frozenset(("overview","camera_angle","lighting","layout",
                            "inspiration"))
SCENE_STATUS=frozenset(("draft","in_review","approved","rejected"))
MAX_SCENES=200
MAX_LINKS=200
MAX_VISUAL_INDEX=500
PROFILE_FIELDS=("project_id","scene_id","display_name","scene_type",
                "layout_notes","lighting_notes","camera_rules",
                "continuity_rules","scene_notes")
DETAIL_FIELDS=("display_name","scene_type","layout_notes","lighting_notes",
               "camera_rules","continuity_rules","scene_notes")


class SceneError(ValueError):
    def __init__(self,reason,status=400):
        super().__init__(reason)
        self.reason=reason
        self.status=status


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS scene_profiles (
      project_id TEXT NOT NULL, scene_id TEXT NOT NULL,
      display_name TEXT NOT NULL, scene_type TEXT NOT NULL,
      layout_notes TEXT NOT NULL, lighting_notes TEXT NOT NULL,
      camera_rules TEXT NOT NULL, continuity_rules TEXT NOT NULL,
      scene_notes TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1,
      status TEXT NOT NULL DEFAULT 'draft',
      approved_revision INTEGER,
      created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
      PRIMARY KEY(project_id,scene_id),
      FOREIGN KEY(project_id) REFERENCES projects(project_id)
    );
    CREATE TABLE IF NOT EXISTS scene_profile_history (
      project_id TEXT NOT NULL, scene_id TEXT NOT NULL, revision INTEGER NOT NULL,
      snapshot_json TEXT NOT NULL, actor TEXT NOT NULL, created_at INTEGER NOT NULL,
      PRIMARY KEY(project_id,scene_id,revision),
      FOREIGN KEY(project_id,scene_id) REFERENCES scene_profiles(project_id,scene_id)
    );
    CREATE TABLE IF NOT EXISTS scene_visual_links (
      project_id TEXT NOT NULL, scene_id TEXT NOT NULL,
      visual_id TEXT NOT NULL, reference_type TEXT NOT NULL,
      linked_at INTEGER NOT NULL,
      PRIMARY KEY(project_id,scene_id,visual_id),
      FOREIGN KEY(project_id,scene_id) REFERENCES scene_profiles(project_id,scene_id),
      FOREIGN KEY(visual_id) REFERENCES visual_media(visual_id)
    );
    CREATE TABLE IF NOT EXISTS scene_review_events (
      seq INTEGER PRIMARY KEY AUTOINCREMENT,
      project_id TEXT NOT NULL, scene_id TEXT NOT NULL,
      revision INTEGER NOT NULL,
      decision TEXT NOT NULL, visual_id TEXT,
      visual_sha256 TEXT, content_sha256 TEXT NOT NULL,
      rationale TEXT NOT NULL, reviewer TEXT NOT NULL, decided_at INTEGER NOT NULL,
      FOREIGN KEY(project_id,scene_id) REFERENCES scene_profiles(project_id,scene_id),
      FOREIGN KEY(visual_id) REFERENCES visual_media(visual_id)
    );
    CREATE INDEX IF NOT EXISTS idx_scene_review_events
      ON scene_review_events(project_id,scene_id,revision,seq);
    CREATE INDEX IF NOT EXISTS idx_scene_visual_links
      ON scene_visual_links(project_id,scene_id);
    """)


def _fields(data,expected):
    if not isinstance(data,dict) or set(data)!=set(expected):
        raise SceneError("invalid_scene_fields")


def _id(value,reason="invalid_scene_id"):
    try:return _ident(value)
    except ProductionError:raise SceneError(reason) from None


def _project(db,value):
    pid=_id(value,"invalid_scene_project")
    if db.execute("SELECT 1 FROM projects WHERE project_id=?",(pid,)).fetchone() is None:
        raise SceneError("scene_project_not_found",404)
    return pid


def _scene(db,pid,sid):
    row=db.execute("SELECT * FROM scene_profiles WHERE project_id=? AND scene_id=?",
                   (pid,sid)).fetchone()
    if row is None:raise SceneError("scene_not_found",404)
    return row


def _text(value,limit=1200,required=False):
    if (not isinstance(value,str) or len(value)>limit or
        any(ord(ch)<32 and ch not in "\n\t" for ch in value) or
        (required and not value.strip())):
        raise SceneError("invalid_scene_text")
    return value.strip()


def _profile_data(data):
    name=_text(data["display_name"],100,True)
    scene_type=data["scene_type"]
    if not isinstance(scene_type,str) or scene_type not in SCENE_TYPES:
        raise SceneError("invalid_scene_type")
    fields={k:_text(data[k],1500 if k=="layout_notes" else 1200,
                   k=="layout_notes")
            for k in ("layout_notes","lighting_notes","camera_rules",
                      "continuity_rules","scene_notes")}
    return dict(display_name=name,scene_type=scene_type,**fields)


def _snapshot(row):
    return json.dumps({
        k:row[k] for k in ("project_id","scene_id","revision",*DETAIL_FIELDS)
    },sort_keys=True,ensure_ascii=False,separators=(",",":"))


def _record_history(db,row,actor):
    db.execute("INSERT INTO scene_profile_history("
               "project_id,scene_id,revision,snapshot_json,actor,created_at)"
               "VALUES(?,?,?,?,?,?)",
               (row["project_id"],row["scene_id"],row["revision"],
                _snapshot(row),actor,int(time.time())))


def _reference(db,pid,visual_id):
    vid=_id(visual_id,"invalid_scene_visual_id")
    row=db.execute("SELECT * FROM visual_media WHERE visual_id=? "
                   "AND project_id=? AND kind='scene'",(vid,pid)).fetchone()
    if row is None:raise SceneError("scene_visual_not_found",404)
    return row


def create_scene(db_path,data,actor):
    _fields(data,PROFILE_FIELDS)
    sid=_id(data["scene_id"])
    clean=_profile_data(data)
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check_audit(db)
        pid=_project(db,data["project_id"])
        with transaction(db):
            if db.execute("SELECT 1 FROM scene_profiles "
                "WHERE project_id=? AND scene_id=?",(pid,sid)).fetchone():
                raise SceneError("scene_already_exists",409)
            if db.execute("SELECT COUNT(*) FROM scene_profiles "
                "WHERE project_id=?",(pid,)).fetchone()[0]>=MAX_SCENES:
                raise SceneError("scene_catalog_full",409)
            now=int(time.time())
            db.execute("INSERT INTO scene_profiles("
                "project_id,scene_id,display_name,scene_type,layout_notes,"
                "lighting_notes,camera_rules,continuity_rules,scene_notes,"
                "revision,status,approved_revision,created_at,updated_at)"
                "VALUES(?,?,?,?,?,?,?,?,?,1,'draft',NULL,?,?)",
                (pid,sid,*[clean[k] for k in DETAIL_FIELDS],now,now))
            row=_scene(db,pid,sid)
            _record_history(db,row,actor)
            _audit(db,actor,"scene.created",sid,
                   {"project_id":pid,"scene_id":sid,"revision":1,
                    "profile_sha256":hashlib.sha256(_snapshot(row).encode()).hexdigest()})
    return {"ok":True,"scene_id":sid,"revision":1,"status":"draft",
            "gpu_action":False}


def update_scene(db_path,data,actor):
    _fields(data,(*PROFILE_FIELDS,"expected_revision"))
    sid=_id(data["scene_id"])
    rev=data["expected_revision"]
    if type(rev) is not int or rev<1:
        raise SceneError("invalid_scene_revision")
    clean=_profile_data(data)
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check_audit(db)
        pid=_project(db,data["project_id"])
        with transaction(db):
            old=_scene(db,pid,sid)
            if old["revision"]!=rev:
                raise SceneError("stale_scene_revision",409)
            if old["status"]=="in_review":
                raise SceneError("scene_pending_review",409)
            now=int(time.time())
            db.execute("UPDATE scene_profiles SET "
                "display_name=?,scene_type=?,layout_notes=?,lighting_notes=?,"
                "camera_rules=?,continuity_rules=?,scene_notes=?,"
                "revision=revision+1,status='draft',updated_at=? "
                "WHERE project_id=? AND scene_id=?",
                (*[clean[k] for k in DETAIL_FIELDS],now,pid,sid))
            row=_scene(db,pid,sid)
            _record_history(db,row,actor)
            _audit(db,actor,"scene.revised",sid,
                {"project_id":pid,"previous_revision":rev,
                 "revision":rev+1,"previously_approved_revision":old["approved_revision"],
                 "profile_sha256":hashlib.sha256(_snapshot(row).encode()).hexdigest()})
    return {"ok":True,"scene_id":sid,"revision":rev+1,"status":"draft",
            "gpu_action":False}


def link_scene_visual(db_path,data,actor):
    _fields(data,("project_id","scene_id","visual_id","reference_type"))
    sid=_id(data["scene_id"])
    typ=data["reference_type"]
    if not isinstance(typ,str) or typ not in REFERENCE_TYPES:
        raise SceneError("invalid_scene_reference_type")
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check_audit(db)
        pid=_project(db,data["project_id"])
        with transaction(db):
            _scene(db,pid,sid)
            visual=_reference(db,pid,data["visual_id"])
            if db.execute("SELECT 1 FROM scene_visual_links WHERE "
                "project_id=? AND scene_id=? AND visual_id=?",
                (pid,sid,visual["visual_id"])).fetchone():
                return {"ok":True,"visual_id":visual["visual_id"],
                        "already_linked":True,"gpu_action":False}
            if db.execute("SELECT COUNT(*) FROM scene_visual_links WHERE "
                "project_id=? AND scene_id=?",(pid,sid)).fetchone()[0]>=MAX_LINKS:
                raise SceneError("scene_reference_limit",409)
            db.execute("INSERT INTO scene_visual_links("
                "project_id,scene_id,visual_id,reference_type,linked_at)"
                "VALUES(?,?,?,?,?)",
                (pid,sid,visual["visual_id"],typ,int(time.time())))
            _audit(db,actor,"scene.visual_linked",sid,
                {"project_id":pid,"visual_id":visual["visual_id"],
                 "episode_id":visual["episode_id"],"kind":"scene",
                 "reference_type":typ,"sha256":visual["sha256"]})
    return {"ok":True,"visual_id":visual["visual_id"],
            "already_linked":False,"gpu_action":False}


def review_scene(db_path,data,actor):
    _fields(data,("project_id","scene_id","expected_revision",
                  "decision","visual_id","rationale"))
    sid=_id(data["scene_id"])
    rev=data["expected_revision"]
    if type(rev) is not int or rev<1:
        raise SceneError("invalid_scene_revision")
    decision=data["decision"]
    if decision not in ("submit","approve","reject"):
        raise SceneError("invalid_scene_decision")
    rationale=_text(data["rationale"],600,True)
    if len(rationale)<8:raise SceneError("scene_review_rationale_required")
    if decision!="approve" and data["visual_id"] is not None:
        raise SceneError("invalid_scene_review_visual")
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check_audit(db)
        pid=_project(db,data["project_id"])
        with transaction(db):
            row=_scene(db,pid,sid)
            if row["revision"]!=rev:
                raise SceneError("stale_scene_revision",409)
            if (decision=="submit" and row["status"]!="draft" or
                decision in ("approve","reject") and row["status"]!="in_review"):
                raise SceneError("invalid_scene_review_transition",409)
            visual=None
            if decision=="approve":
                if data["visual_id"] is None:
                    raise SceneError("scene_approved_visual_required",409)
                visual=_reference(db,pid,data["visual_id"])
                if visual["subject_id"]!=sid:
                    raise SceneError("scene_individual_visual_required",409)
                if db.execute("SELECT 1 FROM scene_visual_links WHERE "
                    "project_id=? AND scene_id=? AND visual_id=?",
                    (pid,sid,visual["visual_id"])).fetchone() is None:
                    raise SceneError("scene_approved_visual_not_linked",409)
            status={"submit":"in_review","approve":"approved",
                    "reject":"rejected"}[decision]
            snap_hash=hashlib.sha256(_snapshot(row).encode()).hexdigest()
            now=int(time.time())
            db.execute("UPDATE scene_profiles SET status=?,"
                "approved_revision=CASE WHEN ?='approved' THEN ? "
                "ELSE approved_revision END,updated_at=? "
                "WHERE project_id=? AND scene_id=?",
                (status,status,rev,now,pid,sid))
            db.execute("INSERT INTO scene_review_events("
                "project_id,scene_id,revision,decision,visual_id,visual_sha256,"
                "content_sha256,rationale,reviewer,decided_at)"
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (pid,sid,rev,decision,
                 visual["visual_id"] if visual is not None else None,
                 visual["sha256"] if visual is not None else None,
                 snap_hash,rationale,actor,now))
            _audit(db,actor,"scene.review_"+decision,sid,
                {"project_id":pid,"scene_id":sid,"revision":rev,
                 "status":status,"visual_id":visual["visual_id"] if visual else None,
                 "visual_sha256":visual["sha256"] if visual else None,
                 "snapshot_sha256":snap_hash})
    return {"ok":True,"scene_id":sid,"revision":rev,"status":status,
            "gpu_action":False}


def list_scenes(db_path,project_id):
    with closing(open_db(db_path,initialize=False)) as db:
        pid=_project(db,project_id)
        profiles=db.execute("SELECT * FROM scene_profiles WHERE project_id=? "
            "ORDER BY scene_id LIMIT 201",(pid,)).fetchall()
        pictures=db.execute(
            "SELECT visual_id,episode_id,subject_id,version,filename,mime,"
            "size_bytes,sha256,created_at FROM visual_media "
            "WHERE project_id=? AND kind='scene' "
            "ORDER BY created_at DESC, visual_id DESC LIMIT 501",(pid,)).fetchall()
        links=db.execute("SELECT scene_id,visual_id,reference_type "
            "FROM scene_visual_links WHERE project_id=?",(pid,)).fetchall()
        linkmap={(r["scene_id"],r["visual_id"]):r["reference_type"] for r in links}
        result=[]
        for row in profiles[:200]:
            info=dict(row)
            sid=info["scene_id"]
            reviews=db.execute("SELECT revision,decision,visual_id,"
                "visual_sha256,rationale,reviewer,decided_at FROM scene_review_events "
                "WHERE project_id=? AND scene_id=? ORDER BY seq DESC LIMIT 12",
                (pid,sid)).fetchall()
            info["reviews"]=[dict(r) for r in reviews]
            canonical=next((dict(r) for r in reviews
                if r["decision"]=="approve" and
                r["revision"]==info["approved_revision"]),None)
            # Historical approval may predate the last twelve review actions.
            if canonical is None and info["approved_revision"] is not None:
                prev=db.execute("SELECT revision,decision,visual_id,"
                    "visual_sha256,rationale,reviewer,decided_at FROM scene_review_events "
                    "WHERE project_id=? AND scene_id=? AND revision=? "
                    "AND decision='approve' ORDER BY seq DESC LIMIT 1",
                    (pid,sid,info["approved_revision"])).fetchone()
                canonical=dict(prev) if prev else None
            info["canonical"]=canonical
            info["visuals"]=[{
                **dict(v),"reference_type":linkmap.get((sid,v["visual_id"]),"overview"),
                "auto_matched":v["subject_id"]==sid,
                "linked":(sid,v["visual_id"]) in linkmap,
            } for v in pictures[:500] if ((sid,v["visual_id"]) in linkmap or
                                    v["subject_id"]==sid)]
            result.append(info)
        return {"ok":True,"project_id":pid,"scene_types":sorted(SCENE_TYPES),
                "reference_types":sorted(REFERENCE_TYPES),
                "scenes":result,"available_visuals":[dict(v) for v in pictures[:500]],
                "truncated":len(profiles)>200 or len(pictures)>500,
                "gpu_action":False}
