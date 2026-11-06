"""Character Library V2: project-level fine-grained, versioned production assets.

Additive to V1. Never moves existing episode images or approves them on import.
Only Microsoft-owner endpoints can mutate/review; no GPU or provider effects.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import closing

from production_core import open_db, transaction, _audit
from character_library import (
    CharacterError, _project, _character_id, _profile, _visual, _check_audit,
    _note,
)

# One catalog rather than one oversized, lossy character-card image.
CATEGORY_FIELDS={
    "profile":("identity_lock","story_function","personality","story_notes"),
    "master":("framing","body_proportions","outfit_id","hair_variant_id"),
    "turnaround":("direction","camera_height","outfit_id","proportions"),
    "face":("expression","intensity","eyeline","viseme"),
    "hair":("region","fringe_partition","length_boundary","ornament_position"),
    "costume":("outfit_id","piece_id","layer_order","silhouette_lock","far_view_rule"),
    "palette":("scope","hex_srgb","material","lighting_rule"),
    "prop":("prop_id","grip_hand","scale_rule","state_rule"),
    "motion":("action_id","key_pose_start","key_pose_middle","key_pose_end"),
    "relationship":("other_character_ids","height_rule","blocking","eyeline"),
    "continuity":("episode_id","shot_id","screen_side","before_state","after_state"),
    "rules":("severity","locked_attribute","forbidden_change","check_method"),
}
CATEGORIES=tuple(CATEGORY_FIELDS)
# No identity-like 'master' or official imagery can become canonical without
# an actual referenced individual image. Metadata-only production definitions
# may be reviewed independently and still do not create an approved pack.
IMAGE_CATEGORIES=frozenset({"master","turnaround","face"})
DIRECTIONS=frozenset({"front","left","right","back","front_left_45",
                      "front_right_45","back_left_45","back_right_45"})
REVIEW_STATES=frozenset({"draft","in_review","approved","rejected"})
MAX_ITEMS_PER_CHARACTER=500
MAX_ASSET_LABEL=110


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS character_assets_v2 (
      item_id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      character_id TEXT NOT NULL,
      category TEXT NOT NULL, subtype TEXT NOT NULL, label TEXT NOT NULL,
      note TEXT NOT NULL, details_json TEXT NOT NULL,
      source_visual_id TEXT, source_sha256 TEXT,
      revision INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'draft',
      created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
      FOREIGN KEY(project_id,character_id)
        REFERENCES character_profiles(project_id,character_id),
      FOREIGN KEY(source_visual_id) REFERENCES visual_media(visual_id)
    );
    CREATE INDEX IF NOT EXISTS idx_character_v2_catalog
      ON character_assets_v2(project_id,character_id,category,status);
    CREATE TABLE IF NOT EXISTS character_assets_v2_history (
      item_id TEXT NOT NULL, revision INTEGER NOT NULL,
      snapshot_json TEXT NOT NULL, actor TEXT NOT NULL, created_at INTEGER NOT NULL,
      PRIMARY KEY(item_id,revision),
      FOREIGN KEY(item_id) REFERENCES character_assets_v2(item_id)
    );
    CREATE TABLE IF NOT EXISTS character_assets_v2_reviews (
      event_id INTEGER PRIMARY KEY AUTOINCREMENT,
      item_id TEXT NOT NULL, revision INTEGER NOT NULL,
      decision TEXT NOT NULL, rationale TEXT NOT NULL, reviewer TEXT NOT NULL,
      content_sha256 TEXT NOT NULL, decided_at INTEGER NOT NULL,
      FOREIGN KEY(item_id) REFERENCES character_assets_v2(item_id)
    );
    CREATE INDEX IF NOT EXISTS idx_character_v2_review
      ON character_assets_v2_reviews(item_id,event_id);
    """)


def _fields(data,expected):
    if not isinstance(data,dict) or set(data)!=set(expected):
        raise CharacterError("invalid_v2_fields")


def _id(item):
    if (not isinstance(item,str) or len(item)!=35 or
            not item.startswith("CA_") or
            not all(ch in "0123456789abcdef" for ch in item[3:])):
        raise CharacterError("invalid_v2_item_id")
    return item


def _asset_row(db,pid,cid,item_id):
    row=db.execute("SELECT * FROM character_assets_v2 "
                   "WHERE project_id=? AND character_id=? AND item_id=?",
                   (pid,cid,_id(item_id))).fetchone()
    if row is None:
        raise CharacterError("v2_asset_not_found",404)
    return row


def _sanitize(data):
    category=data["category"]
    if not isinstance(category,str) or category not in CATEGORY_FIELDS:
        raise CharacterError("invalid_v2_category")
    subtype=data["subtype"]
    if (not isinstance(subtype,str) or not 1<=len(subtype)<=55 or
            not all(c.isascii() and (c.isalnum() or c in "_-") for c in subtype)):
        raise CharacterError("invalid_v2_subtype")
    label=data["label"]
    if (not isinstance(label,str) or not 1<=len(label.strip())<=MAX_ASSET_LABEL
            or any(ord(c)<32 for c in label)):
        raise CharacterError("invalid_v2_label")
    note=_note(data["note"],1800)
    details=data["details"]
    if (not isinstance(details,dict) or
            not set(details)<=set(CATEGORY_FIELDS[category]) or
            len(details)>8 or not details):
        raise CharacterError("invalid_v2_details")
    clean={}
    for key,value in details.items():
        if not isinstance(value,str) or len(value)>220 or (
                any(ord(c)<32 for c in value)):
            raise CharacterError("invalid_v2_details")
        clean[key]=value.strip()
    if category=="turnaround" and clean.get("direction") not in DIRECTIONS:
        raise CharacterError("invalid_v2_direction")
    if category=="rules" and clean.get("severity") not in ("hard","soft"):
        raise CharacterError("invalid_v2_rule")
    if category=="palette" and clean.get("hex_srgb"):
        hex_code=clean["hex_srgb"]
        if (len(hex_code)!=7 or hex_code[0]!="#" or
                any(c not in "0123456789abcdefABCDEF" for c in hex_code[1:])):
            raise CharacterError("invalid_v2_hex_color")
    if category=="continuity" and (
            not clean.get("episode_id") or not clean.get("shot_id")):
        raise CharacterError("invalid_v2_continuity_reference")
    return category,subtype,label.strip(),note,clean


def _reference(db,pid,cid,source_visual_id):
    if source_visual_id is None:return None,None
    image=_visual(db,pid,source_visual_id)
    if image["subject_id"]!=cid and not db.execute(
            "SELECT 1 FROM character_visual_links "
            "WHERE project_id=? AND character_id=? AND visual_id=?",
            (pid,cid,source_visual_id)).fetchone():
        raise CharacterError("v2_source_not_linked",409)
    return image["visual_id"],image["sha256"]


def _snapshot(row):
    return json.dumps({
        k:row[k] for k in ("item_id","project_id","character_id","category",
           "subtype","label","note","details_json","source_visual_id",
           "source_sha256","revision","status")
    },ensure_ascii=False,sort_keys=True,separators=(",",":"))


def _audit_snapshot(db,row,actor):
    db.execute("INSERT INTO character_assets_v2_history "
               "(item_id,revision,snapshot_json,actor,created_at) VALUES(?,?,?,?,?)",
               (row["item_id"],row["revision"],_snapshot(row),actor,int(time.time())))


def create_asset(db_path,data,actor):
    _fields(data,("project_id","character_id","category","subtype","label",
                  "note","details","source_visual_id"))
    cid=_character_id(data["character_id"])
    category,subtype,label,note,details=_sanitize(data)
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check_audit(db)
        pid=_project(db,data["project_id"])
        with transaction(db):
            _profile(db,pid,cid)
            visual_id,digest=_reference(db,pid,cid,data["source_visual_id"])
            if db.execute("SELECT COUNT(*) FROM character_assets_v2 "
                          "WHERE project_id=? AND character_id=?",
                          (pid,cid)).fetchone()[0]>=MAX_ITEMS_PER_CHARACTER:
                raise CharacterError("v2_asset_limit",409)
            item_id="CA_"+secrets.token_hex(16)
            now=int(time.time())
            db.execute("INSERT INTO character_assets_v2 "
                       "(item_id,project_id,character_id,category,subtype,label,"
                       "note,details_json,source_visual_id,source_sha256,created_at,updated_at)"
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (item_id,pid,cid,category,subtype,label,note,
                        json.dumps(details,ensure_ascii=False,sort_keys=True),
                        visual_id,digest,now,now))
            row=_asset_row(db,pid,cid,item_id)
            _audit_snapshot(db,row,actor)
            _audit(db,actor,"character.v2_asset_created",item_id,
                   {"project_id":pid,"character_id":cid,"category":category,
                    "source_visual_id":visual_id,"revision":1,"status":"draft"})
        return {"ok":True,"item_id":item_id,"revision":1,
                "status":"draft","gpu_action":False}


def revise_asset(db_path,data,actor):
    _fields(data,("project_id","character_id","item_id","expected_revision",
                  "category","subtype","label","note","details","source_visual_id"))
    cid=_character_id(data["character_id"])
    category,subtype,label,note,details=_sanitize(data)
    rev=data["expected_revision"]
    if type(rev) is not int or rev<1:
        raise CharacterError("invalid_v2_revision")
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check_audit(db)
        pid=_project(db,data["project_id"])
        with transaction(db):
            row=_asset_row(db,pid,cid,data["item_id"])
            if row["revision"]!=rev:
                raise CharacterError("stale_v2_asset_revision",409)
            if row["status"] not in ("draft","rejected"):
                raise CharacterError("v2_asset_frozen",409)
            visual_id,digest=_reference(db,pid,cid,data["source_visual_id"])
            now=int(time.time())
            db.execute("UPDATE character_assets_v2 SET category=?,subtype=?,"
                       "label=?,note=?,details_json=?,source_visual_id=?,"
                       "source_sha256=?,revision=revision+1,status='draft',updated_at=?"
                       "WHERE item_id=?",
                       (category,subtype,label,note,
                        json.dumps(details,ensure_ascii=False,sort_keys=True),
                        visual_id,digest,now,row["item_id"]))
            updated=_asset_row(db,pid,cid,row["item_id"])
            _audit_snapshot(db,updated,actor)
            _audit(db,actor,"character.v2_asset_revised",row["item_id"],
                   {"project_id":pid,"character_id":cid,
                    "revision":rev+1,"status":"draft"})
        return {"ok":True,"item_id":row["item_id"],"revision":rev+1,
                "status":"draft","gpu_action":False}


def review_asset(db_path,data,actor):
    _fields(data,("project_id","character_id","item_id",
                  "expected_revision","decision","rationale"))
    cid=_character_id(data["character_id"])
    rev=data["expected_revision"]
    decision=data["decision"]
    if type(rev) is not int or rev<1:
        raise CharacterError("invalid_v2_revision")
    if decision not in ("submit","approve","reject"):
        raise CharacterError("invalid_v2_decision")
    rationale=_note(data["rationale"],600)
    if len(rationale)<8:
        raise CharacterError("v2_review_rationale_required")
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check_audit(db)
        pid=_project(db,data["project_id"])
        with transaction(db):
            row=_asset_row(db,pid,cid,data["item_id"])
            if row["revision"]!=rev:
                raise CharacterError("stale_v2_asset_revision",409)
            if ((decision=="submit" and row["status"]!="draft") or
                (decision in ("approve","reject") and row["status"]!="in_review")):
                raise CharacterError("invalid_v2_review_transition",409)
            if decision=="approve" and row["category"] in IMAGE_CATEGORIES:
                if not row["source_visual_id"]:
                    raise CharacterError("v2_visual_required_for_approval",409)
                src=_visual(db,pid,row["source_visual_id"])
                if src["subject_id"]!=cid:
                    raise CharacterError("v2_individual_visual_required",409)
                if src["sha256"]!=row["source_sha256"]:
                    raise CharacterError("v2_source_hash_mismatch",409)
            new_state={"submit":"in_review","approve":"approved",
                       "reject":"rejected"}[decision]
            digest=hashlib.sha256(_snapshot(row).encode("utf-8")).hexdigest()
            now=int(time.time())
            db.execute("UPDATE character_assets_v2 SET status=?,updated_at=? "
                       "WHERE item_id=?",(new_state,now,row["item_id"]))
            db.execute("INSERT INTO character_assets_v2_reviews "
                       "(item_id,revision,decision,rationale,reviewer,"
                       "content_sha256,decided_at) VALUES(?,?,?,?,?,?,?)",
                       (row["item_id"],rev,decision,rationale,actor,digest,now))
            _audit(db,actor,"character.v2_asset_"+decision,row["item_id"],
                   {"project_id":pid,"character_id":cid,
                    "category":row["category"],"revision":rev,
                    "content_sha256":digest,"status":new_state})
        return {"ok":True,"item_id":row["item_id"],"revision":rev,
                "status":new_state,"gpu_action":False}


def list_assets(db_path,project_id,character_id):
    cid=_character_id(character_id)
    with closing(open_db(db_path,initialize=False)) as db:
        pid=_project(db,project_id)
        _profile(db,pid,cid)
        rows=db.execute("SELECT * FROM character_assets_v2 "
                        "WHERE project_id=? AND character_id=? "
                        "ORDER BY category,created_at,item_id LIMIT 501",
                        (pid,cid)).fetchall()
        output=[]
        for r in rows[:500]:
            data=dict(r)
            data["details"]=json.loads(data.pop("details_json"))
            if r["source_visual_id"]:
                vis=_visual(db,pid,r["source_visual_id"])
                data["source_episode_id"]=vis["episode_id"]
                data["source_filename"]=vis["filename"]
            events=db.execute("SELECT decision,rationale,reviewer,decided_at,"
                              "revision,content_sha256 FROM character_assets_v2_reviews "
                              "WHERE item_id=? ORDER BY event_id DESC LIMIT 8",
                              (r["item_id"],)).fetchall()
            data["reviews"]=[dict(e) for e in events]
            output.append(data)
        counts={category:{"total":0,"approved":0} for category in CATEGORIES}
        for x in output:
            counts[x["category"]]["total"]+=1
            if x["status"]=="approved":
                counts[x["category"]]["approved"]+=1
        return {"ok":True,"project_id":pid,"character_id":cid,
                "categories":list(CATEGORIES),"fields":CATEGORY_FIELDS,
                "assets":output,"counts":counts,"truncated":len(rows)>500,
                "pack_status":"not_approved",
                "note":"V2 items do not implicitly approve a character pack or shots."}
