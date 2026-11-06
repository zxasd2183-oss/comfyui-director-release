"""Project-scoped, owner-only character catalog.

Characters are reusable across episodes. Existing immutable episode images are
linked by reference (never copied, deleted or silently made canonical). Brand
visual language is descriptive inspiration, not permission to place logos.
Every mutation verifies and appends to the production audit chain.
No GPU/network/power side effects.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing

from production_core import (_ident, _audit, open_db, transaction, verify_chain,
                             ProductionError)

ROLES = frozenset(("main", "extended"))
REFERENCE_TYPES = frozenset(("character_card", "three_view", "expression",
                            "costume", "prop", "inspiration"))
LOGO_POLICY = "abstract_visual_language_only_no_official_logo"
MAX_CHARACTERS = 150
MAX_LINKS_PER_CHARACTER = 250


class CharacterError(ValueError):
    def __init__(self, reason, status=400):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS character_profiles (
      project_id TEXT NOT NULL, character_id TEXT NOT NULL,
      display_name TEXT NOT NULL, role TEXT NOT NULL,
      brand_basis TEXT NOT NULL, design_language TEXT NOT NULL,
      character_notes TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
      created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
      PRIMARY KEY(project_id,character_id),
      FOREIGN KEY(project_id) REFERENCES projects(project_id)
    );
    CREATE TABLE IF NOT EXISTS character_visual_links (
      project_id TEXT NOT NULL, character_id TEXT NOT NULL,
      visual_id TEXT NOT NULL, reference_type TEXT NOT NULL,
      linked_at INTEGER NOT NULL,
      PRIMARY KEY(project_id,character_id,visual_id),
      FOREIGN KEY(project_id,character_id)
        REFERENCES character_profiles(project_id,character_id),
      FOREIGN KEY(visual_id) REFERENCES visual_media(visual_id)
    );
    CREATE TABLE IF NOT EXISTS character_master_events (
      seq INTEGER PRIMARY KEY AUTOINCREMENT,
      project_id TEXT NOT NULL, character_id TEXT NOT NULL,
      visual_id TEXT, decision TEXT NOT NULL,
      rationale TEXT NOT NULL, reviewer TEXT NOT NULL,
      decided_at INTEGER NOT NULL,
      FOREIGN KEY(project_id,character_id)
        REFERENCES character_profiles(project_id,character_id),
      FOREIGN KEY(visual_id) REFERENCES visual_media(visual_id)
    );
    CREATE INDEX IF NOT EXISTS idx_character_master_history
      ON character_master_events(project_id,character_id,seq);
    """)


def _project(db, project_id):
    try:
        project_id = _ident(project_id)
    except ProductionError:
        raise CharacterError("invalid_character_project") from None
    if not db.execute("SELECT 1 FROM projects WHERE project_id=?",
                      (project_id,)).fetchone():
        raise CharacterError("project_not_found", 404)
    return project_id


def _character_id(value):
    try:
        return _ident(value)
    except ProductionError:
        raise CharacterError("invalid_character_id") from None


def _name(value):
    if (not isinstance(value,str) or not 1 <= len(value.strip()) <= 100 or
            any(ord(c) < 32 for c in value)):
        raise CharacterError("invalid_character_name")
    return value.strip()


def _note(value,limit=1200):
    if (not isinstance(value,str) or len(value)>limit or
            any(ord(c)<32 and c not in "\n\t" for c in value)):
        raise CharacterError("invalid_character_notes")
    return value.strip()


def _profile(db,project_id,character_id):
    row=db.execute("SELECT * FROM character_profiles WHERE project_id=? "
                   "AND character_id=?",(project_id,character_id)).fetchone()
    if row is None:
        raise CharacterError("character_not_found",404)
    return row


def _check_audit(db):
    if not verify_chain(db):
        raise CharacterError("audit_integrity_failure",409)


def _visual(db,project_id,visual_id):
    try:
        visual_id=_ident(visual_id)
    except ProductionError:
        raise CharacterError("invalid_character_visual_id") from None
    row=db.execute("SELECT * FROM visual_media WHERE project_id=? "
                   "AND visual_id=? AND kind='character'",
                   (project_id,visual_id)).fetchone()
    if row is None:
        raise CharacterError("character_visual_not_found",404)
    return row


def create_character(db_path, data, actor):
    required={"project_id","character_id","display_name","role",
              "brand_basis","design_language","character_notes"}
    if not isinstance(data,dict) or set(data)!=required:
        raise CharacterError("invalid_character_fields")
    cid=_character_id(data["character_id"])
    name=_name(data["display_name"])
    role=data["role"]
    if role not in ROLES:raise CharacterError("invalid_character_role")
    brand=_note(data["brand_basis"],600)
    language=_note(data["design_language"],1200)
    notes=_note(data["character_notes"],1200)
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check_audit(db)
        pid=_project(db,data["project_id"])
        with transaction(db):
            if db.execute("SELECT 1 FROM character_profiles "
                          "WHERE project_id=? AND character_id=?",
                          (pid,cid)).fetchone():
                raise CharacterError("character_already_exists",409)
            if db.execute("SELECT COUNT(*) FROM character_profiles "
                          "WHERE project_id=?",(pid,)).fetchone()[0]>=MAX_CHARACTERS:
                raise CharacterError("character_catalog_full",409)
            now=int(time.time())
            db.execute("INSERT INTO character_profiles("
                "project_id,character_id,display_name,role,brand_basis,"
                "design_language,character_notes,created_at,updated_at)"
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (pid,cid,name,role,brand,language,notes,now,now))
            _audit(db,actor,"character.created",cid,
                   {"project_id":pid,"display_name":name,"role":role,
                    "logo_policy":LOGO_POLICY})
    return {"ok":True,"character_id":cid,"revision":1,"gpu_action":False}


def update_character(db_path,data,actor):
    required={"project_id","character_id","expected_revision","display_name",
              "role","brand_basis","design_language","character_notes"}
    if not isinstance(data,dict) or set(data)!=required:
        raise CharacterError("invalid_character_fields")
    cid=_character_id(data["character_id"])
    name=_name(data["display_name"])
    role=data["role"]
    if role not in ROLES:raise CharacterError("invalid_character_role")
    brand=_note(data["brand_basis"],600)
    language=_note(data["design_language"],1200)
    notes=_note(data["character_notes"],1200)
    rev=data["expected_revision"]
    if type(rev) is not int or rev<1:raise CharacterError("invalid_character_revision")
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check_audit(db)
        pid=_project(db,data["project_id"])
        with transaction(db):
            old=_profile(db,pid,cid)
            if old["revision"]!=rev:
                raise CharacterError("stale_character_revision",409)
            db.execute("UPDATE character_profiles SET display_name=?,role=?,"
                       "brand_basis=?,design_language=?,character_notes=?,"
                       "revision=revision+1,updated_at=? "
                       "WHERE project_id=? AND character_id=?",
                       (name,role,brand,language,notes,int(time.time()),pid,cid))
            _audit(db,actor,"character.updated",cid,
                   {"project_id":pid,"previous_revision":rev,
                    "revision":rev+1,"display_name":name,"role":role})
    return {"ok":True,"character_id":cid,"revision":rev+1,"gpu_action":False}


def link_visual(db_path,data,actor):
    if not isinstance(data,dict) or set(data)!={
        "project_id","character_id","visual_id","reference_type"
    }:raise CharacterError("invalid_character_fields")
    cid=_character_id(data["character_id"])
    ref_type=data["reference_type"]
    if ref_type not in REFERENCE_TYPES:
        raise CharacterError("invalid_reference_type")
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check_audit(db)
        pid=_project(db,data["project_id"])
        with transaction(db):
            _profile(db,pid,cid)
            visual=_visual(db,pid,data["visual_id"])
            if db.execute("SELECT 1 FROM character_visual_links "
                          "WHERE project_id=? AND character_id=? AND visual_id=?",
                          (pid,cid,visual["visual_id"])).fetchone():
                return {"ok":True,"visual_id":visual["visual_id"],
                        "already_linked":True,"gpu_action":False}
            if db.execute("SELECT COUNT(*) FROM character_visual_links "
                          "WHERE project_id=? AND character_id=?",
                          (pid,cid)).fetchone()[0]>=MAX_LINKS_PER_CHARACTER:
                raise CharacterError("character_link_limit",409)
            db.execute("INSERT INTO character_visual_links("
                       "project_id,character_id,visual_id,reference_type,linked_at)"
                       "VALUES(?,?,?,?,?)",
                       (pid,cid,visual["visual_id"],ref_type,int(time.time())))
            _audit(db,actor,"character.visual_linked",cid,
                   {"project_id":pid,"visual_id":visual["visual_id"],
                    "episode_id":visual["episode_id"],"reference_type":ref_type})
    return {"ok":True,"visual_id":visual["visual_id"],
            "already_linked":False,"gpu_action":False}


def set_master(db_path,data,actor):
    if not isinstance(data,dict) or set(data)!={
        "project_id","character_id","visual_id","rationale"
    }:raise CharacterError("invalid_character_fields")
    cid=_character_id(data["character_id"])
    rationale=_note(data["rationale"],600)
    if len(rationale)<8:
        raise CharacterError("review_rationale_required")
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check_audit(db)
        pid=_project(db,data["project_id"])
        with transaction(db):
            _profile(db,pid,cid)
            visual=_visual(db,pid,data["visual_id"])
            # Explicitly accept only a known linked/identically-subjected image.
            linked=db.execute(
                "SELECT 1 FROM character_visual_links WHERE project_id=? "
                "AND character_id=? AND visual_id=?",
                (pid,cid,visual["visual_id"])).fetchone()
            if visual["subject_id"]!=cid and not linked:
                raise CharacterError("character_visual_not_linked",409)
            db.execute(
                "INSERT INTO character_master_events("
                "project_id,character_id,visual_id,decision,rationale,reviewer,decided_at)"
                "VALUES(?,?,?,?,?,?,?)",
                (pid,cid,visual["visual_id"],"approved",rationale,actor,int(time.time())))
            _audit(db,actor,"character.master_approved",cid,
                   {"project_id":pid,"visual_id":visual["visual_id"],
                    "episode_id":visual["episode_id"],"sha256":visual["sha256"],
                    "rationale":rationale})
    return {"ok":True,"character_id":cid,"master_visual_id":visual["visual_id"],
            "gpu_action":False}


def list_characters(db_path,project_id):
    with closing(open_db(db_path,initialize=False)) as db:
        pid=_project(db,project_id)
        # No database writes on owner-only GET. Server installation prepares
        # the schema once; new projects need no migration.
        profiles=db.execute(
            "SELECT * FROM character_profiles WHERE project_id=? "
            "ORDER BY CASE role WHEN 'main' THEN 0 ELSE 1 END,character_id",
            (pid,)).fetchall()
        visuals=db.execute(
            "SELECT visual_id,episode_id,subject_id,version,filename,mime,"
            "size_bytes,sha256,created_at FROM visual_media "
            "WHERE project_id=? AND kind='character' "
            "ORDER BY created_at DESC LIMIT 501",(pid,)).fetchall()
        links=db.execute(
            "SELECT character_id,visual_id,reference_type FROM character_visual_links "
            "WHERE project_id=?",(pid,)).fetchall()
        linkmap={(r["character_id"],r["visual_id"]):r["reference_type"] for r in links}
        approvals=db.execute(
            "SELECT e.character_id,e.visual_id,e.rationale,e.reviewer,e.decided_at "
            "FROM character_master_events e "
            "JOIN (SELECT character_id,MAX(seq) AS last_seq "
            "FROM character_master_events WHERE project_id=? GROUP BY character_id) x "
            "ON x.character_id=e.character_id AND x.last_seq=e.seq",
            (pid,)).fetchall()
        approved={row["character_id"]:dict(row) for row in approvals}
        return {"ok":True,"project_id":pid,"logo_policy":LOGO_POLICY,
                "characters":[{
                    **dict(profile),
                    "master":approved.get(profile["character_id"]),
                    "visuals":[{
                        **dict(v),
                        "reference_type":linkmap.get(
                            (profile["character_id"],v["visual_id"]),
                            "character_card" if v["subject_id"]==profile["character_id"]
                            else "inspiration"),
                        "auto_matched":v["subject_id"]==profile["character_id"]
                    } for v in visuals[:500]
                      if (v["subject_id"]==profile["character_id"] or
                          (profile["character_id"],v["visual_id"]) in linkmap)]
                } for profile in profiles],
                "available_visuals":[dict(v) for v in visuals[:500]],
                "truncated":len(visuals)>500}
