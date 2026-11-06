"""Shot-to-character consistency bindings (V2 P2), additive and owner-only.

No pack approval or GPU use. A shot binding stores an immutable, reproducible
snapshot of the selected character/profile version and approved V2 asset
revisions, plus editable composition and prop state. Draft references cannot
become official by being linked to a shot.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing

from production_core import open_db, transaction, _audit, _shot_ident, ProductionError
from character_library import _project, _character_id, _profile, _check_audit, CharacterError
from character_library_v2 import _id, DIRECTIONS

SCREENS=frozenset(("left","center","right","offscreen"))
MAX_BINDINGS_PER_EPISODE=400
MAX_REFERENCES=24
MAX_NOTE=800
SNAPSHOT_FIELDS=("item_id","category","subtype","label","revision",
                 "status","source_visual_id","source_sha256","details_json")


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS shot_character_bindings_v2 (
      project_id TEXT NOT NULL, episode_id TEXT NOT NULL, shot_id TEXT NOT NULL,
      character_id TEXT NOT NULL, binding_revision INTEGER NOT NULL,
      profile_revision INTEGER NOT NULL, profile_snapshot TEXT NOT NULL,
      view_direction TEXT NOT NULL, screen_side TEXT NOT NULL,
      outfit_id TEXT NOT NULL, hair_variant_id TEXT NOT NULL,
      expression TEXT NOT NULL, pose TEXT NOT NULL,
      prop_state_before TEXT NOT NULL, prop_state_after TEXT NOT NULL,
      note TEXT NOT NULL, asset_refs_json TEXT NOT NULL,
      created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
      PRIMARY KEY(project_id,episode_id,shot_id,character_id),
      FOREIGN KEY(project_id,episode_id,shot_id)
        REFERENCES production_shots(project_id,episode_id,shot_id),
      FOREIGN KEY(project_id,character_id)
        REFERENCES character_profiles(project_id,character_id)
    );
    CREATE TABLE IF NOT EXISTS shot_character_binding_history_v2 (
      project_id TEXT NOT NULL, episode_id TEXT NOT NULL, shot_id TEXT NOT NULL,
      character_id TEXT NOT NULL, binding_revision INTEGER NOT NULL,
      snapshot_json TEXT NOT NULL, actor TEXT NOT NULL, created_at INTEGER NOT NULL,
      PRIMARY KEY(project_id,episode_id,shot_id,character_id,binding_revision),
      FOREIGN KEY(project_id,episode_id,shot_id,character_id)
        REFERENCES shot_character_bindings_v2(project_id,episode_id,shot_id,character_id)
    );
    CREATE INDEX IF NOT EXISTS idx_shot_character_bindings_v2
      ON shot_character_bindings_v2(project_id,episode_id,character_id);
    """)


def _exact(data,keys):
    if not isinstance(data,dict) or set(data)!=set(keys):
        raise CharacterError("invalid_shot_binding_fields")


def _episode(db,pid,episode_id):
    try: episode_id=_shot_ident(episode_id)
    except ProductionError:raise CharacterError("invalid_episode_id") from None
    if db.execute("SELECT 1 FROM episodes WHERE project_id=? AND episode_id=?",
                  (pid,episode_id)).fetchone() is None:
        raise CharacterError("episode_not_found",404)
    return episode_id


def _shot(db,pid,eid,shot_id):
    try: shot_id=_shot_ident(shot_id)
    except ProductionError:raise CharacterError("invalid_shot_id") from None
    if db.execute("SELECT 1 FROM production_shots WHERE project_id=? "
                  "AND episode_id=? AND shot_id=?",(pid,eid,shot_id)).fetchone() is None:
        raise CharacterError("shot_not_found",404)
    return shot_id


def _str(value,limit=120):
    if (not isinstance(value,str) or len(value)>limit or
            any(ord(c)<32 and c not in "\n\t" for c in value)):
        raise CharacterError("invalid_shot_binding_value")
    return value.strip()


def _inputs(data):
    view=data["view_direction"]
    side=data["screen_side"]
    if view not in DIRECTIONS or side not in SCREENS:
        raise CharacterError("invalid_shot_orientation")
    if type(data["expected_revision"]) is not int or data["expected_revision"]<0:
        raise CharacterError("invalid_shot_binding_revision")
    fields={k:_str(data[k],MAX_NOTE if k=="note" else 180)
        for k in ("outfit_id","hair_variant_id","expression","pose",
                  "prop_state_before","prop_state_after","note")}
    ids=data["asset_ids"]
    if (not isinstance(ids,list) or len(ids)>MAX_REFERENCES or
            len(ids)!=len(set(x for x in ids if isinstance(x,str))) or
            any(not isinstance(x,str) for x in ids)):
        raise CharacterError("invalid_shot_asset_ids")
    for item in ids:_id(item)
    return view,side,fields,ids


def _approved_refs(db,pid,cid,item_ids):
    if not item_ids:return []
    assets=[]
    for item_id in item_ids:
        row=db.execute("SELECT * FROM character_assets_v2 "
                       "WHERE project_id=? AND character_id=? AND item_id=?",
                       (pid,cid,item_id)).fetchone()
        if row is None:
            raise CharacterError("shot_asset_not_found",404)
        if row["status"]!="approved":
            raise CharacterError("shot_asset_not_approved",409)
        if row["category"] in ("master","turnaround","face"):
            if not row["source_visual_id"]:
                raise CharacterError("shot_asset_missing_visual",409)
            image=db.execute("SELECT sha256,subject_id FROM visual_media "
                             "WHERE project_id=? AND visual_id=?",
                             (pid,row["source_visual_id"])).fetchone()
            if (image is None or image["subject_id"]!=cid or
                    image["sha256"]!=row["source_sha256"]):
                raise CharacterError("shot_asset_source_changed",409)
        approved_event=db.execute(
            "SELECT content_sha256 FROM character_assets_v2_reviews "
            "WHERE item_id=? AND revision=? AND decision='approve' "
            "ORDER BY event_id DESC LIMIT 1",
            (item_id,row["revision"])).fetchone()
        if not approved_event:
            raise CharacterError("shot_asset_approval_missing",409)
        assets.append({**{k:row[k] for k in SNAPSHOT_FIELDS},
                       "approval_hash":approved_event["content_sha256"]})
    return assets


def bind_character(db_path,data,actor):
    _exact(data,("project_id","episode_id","shot_id","character_id",
                 "expected_revision","view_direction","screen_side",
                 "outfit_id","hair_variant_id","expression","pose",
                 "prop_state_before","prop_state_after","note","asset_ids"))
    cid=_character_id(data["character_id"])
    direction,side,values,item_ids=_inputs(data)
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check_audit(db)
        pid=_project(db,data["project_id"])
        eid=_episode(db,pid,data["episode_id"])
        sid=_shot(db,pid,eid,data["shot_id"])
        with transaction(db):
            profile=_profile(db,pid,cid)
            existing=db.execute("SELECT * FROM shot_character_bindings_v2 "
                "WHERE project_id=? AND episode_id=? AND shot_id=? AND character_id=?",
                (pid,eid,sid,cid)).fetchone()
            rev=existing["binding_revision"] if existing else 0
            if rev!=data["expected_revision"]:
                raise CharacterError("stale_shot_binding_revision",409)
            if existing is None and db.execute(
                "SELECT COUNT(*) FROM shot_character_bindings_v2 "
                "WHERE project_id=? AND episode_id=?",
                (pid,eid)).fetchone()[0]>=MAX_BINDINGS_PER_EPISODE:
                raise CharacterError("shot_binding_limit",409)
            refs=_approved_refs(db,pid,cid,item_ids)
            # Freeze these inputs; edits to character profiles/approved
            # asset metadata never mutate an already-bound shot snapshot.
            snap_profile=json.dumps({
                k:profile[k] for k in ("character_id","display_name",
                    "brand_basis","design_language","character_notes","revision")
            },ensure_ascii=False,sort_keys=True)
            snap_assets=json.dumps(refs,ensure_ascii=False,sort_keys=True)
            now=int(time.time())
            if existing:
                db.execute("UPDATE shot_character_bindings_v2 SET "
                    "binding_revision=?,profile_revision=?,profile_snapshot=?,"
                    "view_direction=?,screen_side=?,outfit_id=?,hair_variant_id=?,"
                    "expression=?,pose=?,prop_state_before=?,prop_state_after=?,"
                    "note=?,asset_refs_json=?,updated_at=? "
                    "WHERE project_id=? AND episode_id=? AND shot_id=? AND character_id=?",
                    (rev+1,profile["revision"],snap_profile,direction,side,
                     values["outfit_id"],values["hair_variant_id"],
                     values["expression"],values["pose"],
                     values["prop_state_before"],values["prop_state_after"],
                     values["note"],snap_assets,now,pid,eid,sid,cid))
            else:
                db.execute("INSERT INTO shot_character_bindings_v2("
                    "project_id,episode_id,shot_id,character_id,binding_revision,"
                    "profile_revision,profile_snapshot,view_direction,screen_side,"
                    "outfit_id,hair_variant_id,expression,pose,prop_state_before,"
                    "prop_state_after,note,asset_refs_json,created_at,updated_at)"
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid,eid,sid,cid,1,profile["revision"],snap_profile,
                     direction,side,values["outfit_id"],values["hair_variant_id"],
                     values["expression"],values["pose"],
                     values["prop_state_before"],values["prop_state_after"],
                     values["note"],snap_assets,now,now))
            latest=db.execute("SELECT * FROM shot_character_bindings_v2 WHERE "
                "project_id=? AND episode_id=? AND shot_id=? AND character_id=?",
                (pid,eid,sid,cid)).fetchone()
            record={k:latest[k] for k in latest.keys()
                    if k not in ("created_at","updated_at")}
            frozen=json.dumps(record,ensure_ascii=False,sort_keys=True)
            db.execute("INSERT INTO shot_character_binding_history_v2 "
                "(project_id,episode_id,shot_id,character_id,binding_revision,"
                "snapshot_json,actor,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (pid,eid,sid,cid,rev+1,frozen,actor,now))
            _audit(db,actor,"character.shot_binding_saved",
                   f"{eid}.{sid}.{cid}",{
                       "project_id":pid,"revision":rev+1,
                       "profile_revision":profile["revision"],
                       "approved_asset_ids":item_ids,
                       "snapshot_sha256":hashlib.sha256(
                           frozen.encode("utf8")).hexdigest()})
    return {"ok":True,"episode_id":eid,"shot_id":sid,"character_id":cid,
            "revision":rev+1,"binding_status":"planning_only",
            "approved_asset_count":len(item_ids),"gpu_action":False}


def _continuity(bindings,order):
    by_char={}
    for b in bindings:
        by_char.setdefault(b["character_id"],[]).append(b)
    findings=[]
    for cid,items in by_char.items():
        ordered=sorted(items,key=lambda b:order[b["shot_id"]])
        for before,after in zip(ordered,ordered[1:]):
            previous_ordinal=order[before["shot_id"]]
            current_ordinal=order[after["shot_id"]]
            # Never imply continuity between non-adjacent appearances.
            if current_ordinal!=previous_ordinal+1:continue
            for field,rule in (("outfit_id","costume_changed"),
                               ("hair_variant_id","hair_variant_changed")):
                a,b=before[field],after[field]
                if a and b and a!=b:
                    findings.append({
                        "character_id":cid,"from_shot":before["shot_id"],
                        "to_shot":after["shot_id"],"rule":rule,
                        "before":a,"after":b,"severity":"review"})
            a,b=before["prop_state_after"],after["prop_state_before"]
            if a and b and a!=b:
                findings.append({
                    "character_id":cid,"from_shot":before["shot_id"],
                    "to_shot":after["shot_id"],"rule":"prop_state_mismatch",
                    "before":a,"after":b,"severity":"review"})
    return findings


def list_bindings(db_path,project_id,episode_id):
    with closing(open_db(db_path,initialize=False)) as db:
        pid=_project(db,project_id)
        eid=_episode(db,pid,episode_id)
        shots=db.execute("SELECT shot_id,ordinal,duration_ms FROM production_shots "
                         "WHERE project_id=? AND episode_id=? ORDER BY ordinal",
                         (pid,eid)).fetchall()
        order={r["shot_id"]:r["ordinal"] for r in shots}
        rows=db.execute("SELECT * FROM shot_character_bindings_v2 WHERE "
                        "project_id=? AND episode_id=? ORDER BY shot_id,character_id",
                        (pid,eid)).fetchall()
        result=[]
        for row in rows:
            record=dict(row)
            record["asset_refs"]=json.loads(record.pop("asset_refs_json"))
            record["profile_snapshot"]=json.loads(record["profile_snapshot"])
            # Ready for composition planning only until explicit character pack
            # approval is implemented; no automatic storyboard/video promotion.
            record["production_ready"]=False
            record["readiness_reason"]="character_pack_not_approved"
            result.append(record)
        return {"ok":True,"project_id":pid,"episode_id":eid,
                "shots":[dict(s) for s in shots],
                "bindings":result,"findings":_continuity(result,order),
                "binding_count":len(result),"can_generate_final":False,
                "note":"Draft shot mappings only. No approved character pack exists."}
