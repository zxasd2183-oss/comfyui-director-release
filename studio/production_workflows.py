"""Director Studio production work units: real project/shot assets, not fake statuses.

Owner-only CRUD/review for prop specifications, shot staging, storyboard frames,
clay/white-model camera plans, video production orders, and dependency tasks.
No ComfyUI, GPU control, remote fetching, AI generation, arbitrary file writes,
or fake 'render succeeded' transitions. Those need separate execution plumbing.

Each record includes project/episode/shot scopes and immutable revision snapshots.
Accepted visual IDs must be owner-imported, image-verified, same project/kind
and per-subject (no group/reference composites as approved masters).
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from contextlib import closing

from production_core import (
    open_db, transaction, _audit, _ident, _shot_ident, ProductionError, verify_chain
)

# This is also the form configuration sent to Studio; no ad-hoc HTML attributes
# or client-supplied fields are executed or interpreted as markup.
SCHEMAS={
    "props":{
        "scope":"project","image_kind":"prop",
        "fields":{
            "name":("名称","text"),"use":("剧情用途","text"),
            "dimensions":("尺寸 / 人物比例","text"),
            "materials":("材质 / 反射特性","text"),
            "palette":("配色 / 特征","text"),
            "grip":("握持 / 穿戴关系","text"),
            "turnaround":("三视图 / 旋转规则","text"),
            "continuity":("连续性禁止项","text")}},
    "shot_plans":{
        "scope":"shot","image_kind":None,
        "fields":{
            "title":("镜头标题","text"),"story":("画面 / 剧情描述","text"),
            "scene_id":("场景编号","text"),
            "prop_ids":("出场道具编号（英文逗号分隔）","text"),
            "shot_size":("景别","text"),"camera_angle":("机位 / 角度","text"),
            "composition":("构图与视线","text"),
            "movement":("摄影机运动","text"),"transition":("剪辑衔接","text")}},
    "storyboards":{
        "scope":"shot","image_kind":"storyboard",
        "fields":{
            "shot_size":("景别","text"),"composition":("画面构图","text"),
            "characters":("角色与情绪","text"),
            "lighting":("光照与颜色","text"),
            "reference_notes":("素材引用与修改依据","text"),
            "revision_goal":("本版改图目标 / 局部重绘区域","text")}},
    "white_models":{
        "scope":"shot","image_kind":None,
        "fields":{
            "stage_width":("场地宽度（米）","number"),
            "stage_depth":("场地深度（米）","number"),
            "camera_x":("相机 X","number"),"camera_y":("相机 Y","number"),
            "camera_z":("相机高度 Z","number"),
            "camera_yaw":("相机朝向 °","number"),
            "camera_pitch":("相机俯仰 °","number"),
            "focal_mm":("镜头焦距 mm","number"),
            "actor_x":("人物 X","number"),"actor_y":("人物 Y","number"),
            "actor_height":("人物高度（米）","number"),
            "prop_x":("道具 X","number"),"prop_y":("道具 Y","number"),
            "keyframes":("动作关键帧说明","text"),
            "camera_path":("相机运动路径","text"),
            "quality":("白模精度（粗/精）","text")}},
    "video_plans":{
        "scope":"shot","image_kind":None,
        "fields":{
            "model":("目标视频工作流 / 模型","text"),
            "prompt":("画面运动描述","text"),
            "negative":("禁止变化与负面约束","text"),
            "fps":("帧率","number"),
            "width":("宽度","number"),"height":("高度","number"),
            "duration":("镜头秒数","number"),
            "seed":("随机种子 / 复现编号","text"),
            "input_package":("批准输入清单 / 备注","text"),
            "output_note":("输出与返工记录","text")}},
    "tasks":{
        "scope":"project","image_kind":None,
        "fields":{
            "title":("任务名称","text"),"owner":("负责人","text"),
            "workstream":("关联模块","text"),
            "target":("关联剧集 / 镜头 / 资产","text"),
            "prerequisites":("前置任务编号（逗号分隔）","text"),
            "priority":("优先级（P0/P1/P2）","text"),
            "acceptance":("验收标准","text"),
            "outcome":("完成证明 / 结果说明","text")}},
    "settings":{
        "scope":"episode","image_kind":None,
        "fields":{
            "aspect":("画幅（例如 9:16）","text"),
            "width":("画面宽度 px","number"),"height":("画面高度 px","number"),
            "fps":("帧率","number"),"color":("颜色空间","text"),
            "naming":("镜头命名规则","text"),
            "pipeline":("默认制作工作流","text"),
            "notes":("项目交付规范","text")}}
}
KINDS=tuple(SCHEMAS)
STATUSES={"draft","in_review","approved","rejected"}
SHOT_KINDS={k for k,v in SCHEMAS.items() if v["scope"]=="shot"}
EPISODE_KINDS={k for k,v in SCHEMAS.items() if v["scope"]=="episode"}
MAX_ENTRIES_PER_SCOPE=700
MAX_VALUE=2000


class WorkflowError(ValueError):
    def __init__(self,reason,status=400):
        self.reason,self.status=reason,status
        super().__init__(reason)


def prepare_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS studio_work_units (
      project_id TEXT NOT NULL, episode_id TEXT NOT NULL,
      kind TEXT NOT NULL, unit_id TEXT NOT NULL,
      shot_id TEXT NOT NULL DEFAULT '',
      fields_json TEXT NOT NULL, note TEXT NOT NULL,
      source_visual_id TEXT, source_sha256 TEXT,
      revision INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
      approved_revision INTEGER,
      created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
      PRIMARY KEY(project_id,episode_id,kind,unit_id),
      FOREIGN KEY(project_id) REFERENCES projects(project_id),
      FOREIGN KEY(source_visual_id) REFERENCES visual_media(visual_id)
    );
    CREATE TABLE IF NOT EXISTS studio_work_unit_history (
      project_id TEXT NOT NULL, episode_id TEXT NOT NULL,
      kind TEXT NOT NULL, unit_id TEXT NOT NULL,
      revision INTEGER NOT NULL, snapshot_json TEXT NOT NULL,
      actor TEXT NOT NULL, at INTEGER NOT NULL,
      PRIMARY KEY(project_id,episode_id,kind,unit_id,revision),
      FOREIGN KEY(project_id,episode_id,kind,unit_id)
        REFERENCES studio_work_units(project_id,episode_id,kind,unit_id)
    );
    CREATE TABLE IF NOT EXISTS studio_work_unit_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      project_id TEXT NOT NULL, episode_id TEXT NOT NULL,
      kind TEXT NOT NULL, unit_id TEXT NOT NULL,
      revision INTEGER NOT NULL, decision TEXT NOT NULL,
      rationale TEXT NOT NULL, reviewer TEXT NOT NULL,
      snapshot_sha256 TEXT NOT NULL,
      visual_sha256 TEXT, at INTEGER NOT NULL,
      FOREIGN KEY(project_id,episode_id,kind,unit_id)
        REFERENCES studio_work_units(project_id,episode_id,kind,unit_id)
    );
    CREATE INDEX IF NOT EXISTS idx_workflow_units_by_episode
      ON studio_work_units(project_id,episode_id,kind,status);
    """)


def _exact(data,required):
    if not isinstance(data,dict) or set(data)!=set(required):
        raise WorkflowError("invalid_workflow_fields")


def _kind(value):
    if value not in SCHEMAS:raise WorkflowError("invalid_workflow_kind")
    return value


def _ident_safe(value):
    try:return _ident(value)
    except ProductionError:raise WorkflowError("invalid_workflow_identifier") from None


def _shot_safe(value):
    try:return _shot_ident(value)
    except ProductionError:raise WorkflowError("invalid_workflow_shot_id") from None


def _check(db):
    if not verify_chain(db):raise WorkflowError("audit_integrity_failure",409)


def _scope(db,pid,kind,episode,shot,unit):
    pid=_ident_safe(pid);_kind(kind)
    if db.execute("SELECT 1 FROM projects WHERE project_id=?",(pid,)).fetchone() is None:
        raise WorkflowError("project_not_found",404)
    scope=SCHEMAS[kind]["scope"]
    if scope=="project":
        if episode or shot:raise WorkflowError("project_scope_expected")
        return pid,"","",_ident_safe(unit)
    eid=_ident_safe(episode)
    if db.execute("SELECT 1 FROM episodes WHERE project_id=? AND episode_id=?",
                  (pid,eid)).fetchone() is None:
        raise WorkflowError("episode_not_found",404)
    if scope=="episode":
        if shot:raise WorkflowError("episode_scope_expected")
        return pid,eid,"",_ident_safe(unit)
    sid=_shot_safe(shot)
    if db.execute("SELECT 1 FROM production_shots WHERE project_id=? "
                  "AND episode_id=? AND shot_id=?",(pid,eid,sid)).fetchone() is None:
        raise WorkflowError("shot_not_found",404)
    if unit!=sid:
        # one fully versioned composition/white-model/storyboard/video plan per shot
        raise WorkflowError("unit_id_must_match_shot_id")
    return pid,eid,sid,sid


def _validated_fields(kind,value):
    if not isinstance(value,dict) or not value:
        raise WorkflowError("workflow_details_required")
    allowed=SCHEMAS[kind]["fields"]
    if set(value)-set(allowed):
        raise WorkflowError("unsupported_workflow_field")
    clean={}
    for key,raw in value.items():
        if not isinstance(raw,str) or len(raw)>MAX_VALUE or any(
            ord(c)<32 and c not in "\n\t" for c in raw
        ):raise WorkflowError("invalid_workflow_value")
        raw=raw.strip()
        if raw:
            if allowed[key][1]=="number":
                try:
                    number=float(raw)
                    if not (-100000<=number<=100000):raise ValueError
                except (ValueError,OverflowError):
                    raise WorkflowError("invalid_workflow_number") from None
                if key in ("stage_width","stage_depth","actor_height",
                           "focal_mm","duration","fps","width","height") and number<=0:
                    raise WorkflowError("positive_workflow_number_required")
            clean[key]=raw
    if not clean:raise WorkflowError("workflow_details_required")
    if kind=="white_models" and clean.get("keyframes"):
        try:
            frames=json.loads(clean["keyframes"])
            keys={"t","actor_x","actor_y","prop_x","prop_y",
                  "camera_x","camera_y","camera_z","camera_yaw"}
            if not isinstance(frames,list) or not 1<=len(frames)<=60:
                raise ValueError
            previous=-1.0
            for frame in frames:
                if not isinstance(frame,dict) or not set(frame)<=keys or "t" not in frame:
                    raise ValueError
                t=frame["t"]
                if type(t) not in (float,int) or not 0<=t<=120 or t<=previous:
                    raise ValueError
                previous=t
                for key,value in frame.items():
                    if type(value) not in (float,int) or not -1000<=value<=1000:
                        raise ValueError
        except (ValueError,TypeError,OverflowError):
            raise WorkflowError("invalid_white_model_keyframes") from None
    return clean


def _visual(db,pid,eid,kind,uid,visual_id):
    if visual_id is None:return None
    vid=_ident_safe(visual_id)
    visual=db.execute("SELECT * FROM visual_media WHERE visual_id=? AND project_id=?",
                      (vid,pid)).fetchone()
    if visual is None:raise WorkflowError("workflow_visual_not_found",404)
    if visual["kind"]!=SCHEMAS[kind]["image_kind"]:
        raise WorkflowError("workflow_visual_type_mismatch",409)
    if visual["subject_id"]!=uid:
        raise WorkflowError("workflow_individual_visual_required",409)
    if eid and visual["episode_id"]!=eid:
        raise WorkflowError("workflow_episode_visual_mismatch",409)
    return visual


def _dependencies(db,pid,eid,kind,fields,unit_id=""):
    if kind=="shot_plans":
        sid=fields.get("scene_id","")
        if sid:
            _ident_safe(sid)
            if db.execute("SELECT 1 FROM scene_profiles WHERE project_id=? AND scene_id=?",
                          (pid,sid)).fetchone() is None:
                raise WorkflowError("scene_dependency_not_found",409)
        refs=[s.strip() for s in fields.get("prop_ids","").split(",") if s.strip()]
        if len(refs)>32 or len(refs)!=len(set(refs)):
            raise WorkflowError("invalid_prop_dependencies")
        for ref in refs:
            _ident_safe(ref)
            if db.execute("SELECT 1 FROM studio_work_units WHERE project_id=? "
                 "AND episode_id='' AND kind='props' AND unit_id=?",
                 (pid,ref)).fetchone() is None:
                raise WorkflowError("prop_dependency_not_found",409)
    if kind=="tasks":
        refs=[s.strip() for s in fields.get("prerequisites","").split(",") if s.strip()]
        if len(refs)>30 or len(refs)!=len(set(refs)):
            raise WorkflowError("invalid_task_dependencies")
        for ref in refs:_ident_safe(ref)
        # A task cannot depend on itself or on a dependency cycle. Resolve
        # every link in this same project's committed task graph, not just
        # syntactically valid IDs that can never be completed.
        queue=list(refs)
        seen=set()
        while queue:
            ref=queue.pop()
            if ref==unit_id:
                raise WorkflowError("circular_task_dependency",409)
            if ref in seen:continue
            seen.add(ref)
            if len(seen)>MAX_ENTRIES_PER_SCOPE:
                raise WorkflowError("invalid_task_dependencies",409)
            task=db.execute("SELECT fields_json FROM studio_work_units "
                "WHERE project_id=? AND episode_id='' AND kind='tasks' "
                "AND unit_id=?",(pid,ref)).fetchone()
            if task is None:
                raise WorkflowError("task_dependency_not_found",409)
            child=json.loads(task["fields_json"])
            queue.extend(x.strip() for x in
                child.get("prerequisites","").split(",") if x.strip())
    if kind=="settings":
        asp=fields.get("aspect","")
        if asp and asp not in ("9:16","16:9","1:1","4:3","3:4","2.39:1"):
            raise WorkflowError("unsupported_aspect_ratio")


def _record(db,pid,eid,kind,uid):
    row=db.execute("SELECT * FROM studio_work_units WHERE "
                   "project_id=? AND episode_id=? AND kind=? AND unit_id=?",
                   (pid,eid,kind,uid)).fetchone()
    return row


def _snapshot(row):
    return json.dumps({k:row[k] for k in (
        "project_id","episode_id","kind","unit_id","shot_id","revision",
        "fields_json","note","source_visual_id","source_sha256"
    )},sort_keys=True,ensure_ascii=False,separators=(",",":"))


def _info(row):
    item=dict(row)
    item["fields"]=json.loads(item.pop("fields_json"))
    return item


def save_unit(db_path,data,actor):
    _exact(data,("project_id","episode_id","kind","unit_id","shot_id",
                 "expected_revision","fields","note","source_visual_id"))
    kind=_kind(data["kind"])
    values=_validated_fields(kind,data["fields"])
    note=data["note"]
    if (not isinstance(note,str) or len(note)>MAX_VALUE or
            any(ord(c)<32 and c not in "\n\t" for c in note)):
        raise WorkflowError("invalid_workflow_note")
    rev=data["expected_revision"]
    if type(rev) is not int or rev<0 or rev>100000:
        raise WorkflowError("invalid_workflow_revision")
    with closing(open_db(db_path)) as db:
        prepare_schema(db)
        _check(db)
        pid,eid,sid,uid=_scope(db,data["project_id"],kind,data["episode_id"],
                                data["shot_id"],data["unit_id"])
        with transaction(db):
            old=_record(db,pid,eid,kind,uid)
            if rev!=(old["revision"] if old else 0):
                raise WorkflowError("stale_workflow_revision",409)
            if old is not None and old["status"]=="in_review":
                raise WorkflowError("work_unit_in_review",409)
            if old is None and db.execute(
                "SELECT COUNT(*) FROM studio_work_units WHERE "
                "project_id=? AND episode_id=? AND kind=?",
                (pid,eid,kind)).fetchone()[0]>=MAX_ENTRIES_PER_SCOPE:
                raise WorkflowError("workflow_catalog_full",409)
            _dependencies(db,pid,eid,kind,values,uid)
            visual=_visual(db,pid,eid,kind,uid,data["source_visual_id"])
            now=int(time.time())
            src=visual["visual_id"] if visual else None
            digest=visual["sha256"] if visual else None
            if old is None:
                db.execute("INSERT INTO studio_work_units("
                           "project_id,episode_id,kind,unit_id,shot_id,fields_json,note,"
                           "source_visual_id,source_sha256,revision,status,"
                           "approved_revision,created_at,updated_at)"
                           "VALUES(?,?,?,?,?,?,?,?,?,1,'draft',NULL,?,?)",
                           (pid,eid,kind,uid,sid,json.dumps(values,ensure_ascii=False,
                            sort_keys=True),note.strip(),src,digest,now,now))
            else:
                db.execute("UPDATE studio_work_units SET "
                           "fields_json=?,note=?,source_visual_id=?,source_sha256=?,"
                           "revision=revision+1,status='draft',updated_at=? "
                           "WHERE project_id=? AND episode_id=? AND kind=? AND unit_id=?",
                           (json.dumps(values,ensure_ascii=False,sort_keys=True),
                            note.strip(),src,digest,now,pid,eid,kind,uid))
            row=_record(db,pid,eid,kind,uid)
            snap=_snapshot(row)
            db.execute("INSERT INTO studio_work_unit_history("
                       "project_id,episode_id,kind,unit_id,revision,"
                       "snapshot_json,actor,at) VALUES(?,?,?,?,?,?,?,?)",
                       (pid,eid,kind,uid,row["revision"],snap,actor,now))
            _audit(db,actor,"workflow.saved",f"{pid}/{eid}/{kind}/{uid}",{
                "revision":row["revision"],"status":"draft",
                "snapshot_sha256":hashlib.sha256(snap.encode()).hexdigest()})
    return {"ok":True,"project_id":pid,"episode_id":eid,"kind":kind,
            "unit_id":uid,"revision":rev+1,"status":"draft","gpu_action":False}


def review_unit(db_path,data,actor):
    _exact(data,("project_id","episode_id","kind","unit_id",
                 "expected_revision","decision","rationale"))
    kind=_kind(data["kind"]);rev=data["expected_revision"]
    if type(rev) is not int or rev<1:raise WorkflowError("invalid_workflow_revision")
    dec=data["decision"]
    if dec not in ("submit","approve","reject"):
        raise WorkflowError("invalid_workflow_review_action")
    why=data["rationale"]
    if not isinstance(why,str) or not 8<=len(why.strip())<=600:
        raise WorkflowError("workflow_review_reason_required")
    with closing(open_db(db_path)) as db:
        _check(db)
        # The server has prepared the tables on startup; do not create schema
        # when browsing. Mutations validate project and exact revision.
        pid=_ident_safe(data["project_id"])
        eid=data["episode_id"]
        uid=data["unit_id"]
        if not isinstance(eid,str) or not isinstance(uid,str):
            raise WorkflowError("invalid_workflow_identifier")
        with transaction(db):
            row=_record(db,pid,eid,kind,uid)
            if row is None:raise WorkflowError("work_unit_not_found",404)
            _scope(db,pid,kind,eid,row["shot_id"],uid)
            if row["revision"]!=rev:
                raise WorkflowError("stale_workflow_revision",409)
            if ((dec=="submit" and row["status"]!="draft") or
                (dec in ("approve","reject") and row["status"]!="in_review")):
                raise WorkflowError("invalid_workflow_review_transition",409)
            if dec=="approve":
                fields=json.loads(row["fields_json"])
                if kind=="white_models" and fields.get("quality","").strip() not in (
                    "","粗白模","rough"):
                    raise WorkflowError("fine_white_model_engine_not_connected",409)
                if kind=="shot_plans":
                    scene_id=fields.get("scene_id")
                    if not scene_id:
                        raise WorkflowError("approved_scene_required",409)
                    scene=db.execute("SELECT status FROM scene_profiles WHERE "
                        "project_id=? AND scene_id=?",(pid,scene_id)).fetchone()
                    if not scene or scene["status"]!="approved":
                        raise WorkflowError("scene_not_approved",409)
                    for prop_id in [x.strip() for x in
                        fields.get("prop_ids","").split(",") if x.strip()]:
                        prop=_record(db,pid,"","props",prop_id)
                        if not prop or prop["status"]!="approved":
                            raise WorkflowError("prop_not_approved",409)
                if kind in ("storyboards","white_models"):
                    prior=_record(db,pid,eid,"shot_plans",uid)
                    if prior is None or prior["status"]!="approved":
                        raise WorkflowError("shot_plan_not_approved",409)
                if kind=="white_models":
                    board=_record(db,pid,eid,"storyboards",uid)
                    if board is None or board["status"]!="approved":
                        raise WorkflowError("storyboard_not_approved",409)
                    for key in ("stage_width","stage_depth","camera_z","focal_mm",
                                "actor_height"):
                        if key not in fields:raise WorkflowError(
                            "white_model_geometry_incomplete",409)
                if kind=="tasks" and not fields.get("outcome"):
                    raise WorkflowError("task_completion_evidence_required",409)
                if kind=="settings":
                    for key in ("aspect","fps","width","height"):
                        if key not in fields:raise WorkflowError(
                            "project_format_incomplete",409)
                    aspect=fields["aspect"]
                    expected={"9:16":9/16,"16:9":16/9,"1:1":1,
                        "4:3":4/3,"3:4":3/4,"2.39:1":2.39}[aspect]
                    width=float(fields["width"])
                    height=float(fields["height"])
                    if abs(width/height-expected)>0.02:
                        raise WorkflowError("project_aspect_does_not_match_resolution",409)
                if kind in ("storyboards","props") and not row["source_visual_id"]:
                    raise WorkflowError("individual_reference_image_required",409)
                if row["source_visual_id"]:
                    image=_visual(db,pid,eid,kind,uid,row["source_visual_id"])
                    if image["sha256"]!=row["source_sha256"]:
                        raise WorkflowError("source_image_changed",409)
                if kind=="video_plans":
                    # A video job specification is not an executed/rended clip.
                    # Do not label it approved until actual render validation
                    # exists; it can be submitted/rejected as a planning record.
                    raise WorkflowError("video_render_not_connected",409)
                if kind=="tasks":
                    deps=[s.strip() for s in json.loads(row["fields_json"]).get(
                        "prerequisites","").split(",") if s.strip()]
                    for dep in deps:
                        other=_record(db,pid,"","tasks",dep)
                        if other is None or other["status"]!="approved":
                            raise WorkflowError("task_dependency_unfinished",409)
            status={"submit":"in_review","approve":"approved",
                    "reject":"rejected"}[dec]
            now=int(time.time())
            snap=_snapshot(row)
            digest=hashlib.sha256(snap.encode()).hexdigest()
            db.execute("UPDATE studio_work_units SET status=?,"
                       "approved_revision=CASE WHEN ?='approved' THEN ? "
                       "ELSE approved_revision END,updated_at=? "
                       "WHERE project_id=? AND episode_id=? AND kind=? AND unit_id=?",
                       (status,status,rev,now,pid,eid,kind,uid))
            db.execute("INSERT INTO studio_work_unit_reviews("
                       "project_id,episode_id,kind,unit_id,revision,decision,"
                       "rationale,reviewer,snapshot_sha256,visual_sha256,at)"
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (pid,eid,kind,uid,rev,dec,why.strip(),actor,
                        digest,row["source_sha256"],now))
            _audit(db,actor,"workflow.review_"+dec,f"{pid}/{eid}/{kind}/{uid}",{
                "revision":rev,"snapshot_sha256":digest,"status":status,
                "source_sha256":row["source_sha256"]})
    return {"ok":True,"kind":kind,"unit_id":uid,"status":status,
            "revision":rev,"gpu_action":False}



def _video_blockers(db,pid,eid,sid):
    """Conservative readiness list. Approved planning != rendered media."""
    problems=[]
    spec=db.execute("SELECT COUNT(*) FROM studio_work_units WHERE "
        "project_id=? AND episode_id=? AND kind='settings' "
        "AND status='approved'",(pid,eid)).fetchone()[0]
    if not spec:problems.append("project_spec_not_approved")
    for kind in ("shot_plans","storyboards","white_models"):
        upstream=_record(db,pid,eid,kind,sid)
        if upstream is None or upstream["status"]!="approved":
            problems.append(kind+"_not_approved")
    shot=_record(db,pid,eid,"shot_plans",sid)
    if shot and shot["status"]=="approved":
        fields=json.loads(shot["fields_json"])
        scene_id=fields.get("scene_id")
        if scene_id:
            scene=db.execute("SELECT status FROM scene_profiles WHERE "
                "project_id=? AND scene_id=?",(pid,scene_id)).fetchone()
            if not scene or scene["status"]!="approved":
                problems.append("scene_revision_not_approved")
        for prop_id in [x.strip() for x in
            fields.get("prop_ids","").split(",") if x.strip()]:
            prop=_record(db,pid,"","props",prop_id)
            if not prop or prop["status"]!="approved":
                problems.append("prop_not_approved:"+prop_id)
    bindings=db.execute("SELECT character_id FROM shot_character_bindings_v2 "
        "WHERE project_id=? AND episode_id=? AND shot_id=?",
        (pid,eid,sid)).fetchall()
    for record in bindings:
        character_id=record["character_id"]
        master=db.execute("SELECT visual_id FROM character_master_events "
            "WHERE project_id=? AND character_id=? AND decision='approved' "
            "ORDER BY seq DESC LIMIT 1",(pid,character_id)).fetchone()
        if master is None:
            problems.append("character_master_not_approved:"+character_id)
    # Integration contract explicitly says the Comfy renderer/result verifier
    # is not present. Never return an unqualified ready=True flag.
    problems.append("video_render_executor_not_connected")
    return problems


def list_units(db_path,project_id,kind,episode_id=""):
    kind=_kind(kind)
    with closing(open_db(db_path,initialize=False)) as db:
        pid=_ident_safe(project_id)
        if db.execute("SELECT 1 FROM projects WHERE project_id=?",(pid,)).fetchone() is None:
            raise WorkflowError("project_not_found",404)
        eid=episode_id
        if SCHEMAS[kind]["scope"]!="project":
            eid=_ident_safe(eid)
            if db.execute("SELECT 1 FROM episodes WHERE project_id=? "
                          "AND episode_id=?",(pid,eid)).fetchone() is None:
                raise WorkflowError("episode_not_found",404)
        elif eid:
            raise WorkflowError("project_scope_expected")
        rows=db.execute("SELECT * FROM studio_work_units WHERE project_id=? "
                        "AND episode_id=? AND kind=? ORDER BY updated_at DESC,"
                        "unit_id LIMIT 701",(pid,eid,kind)).fetchall()
        items=[]
        for row in rows[:700]:
            info=_info(row)
            reviews=db.execute("SELECT decision,rationale,reviewer,revision,at "
                "FROM studio_work_unit_reviews WHERE project_id=? AND episode_id=? "
                "AND kind=? AND unit_id=? ORDER BY id DESC LIMIT 8",
                (pid,eid,kind,row["unit_id"])).fetchall()
            info["reviews"]=[dict(x) for x in reviews]
            if kind=="video_plans":
                info["blockers"]=_video_blockers(db,pid,eid,row["shot_id"])
                info["rendered"]=False
            items.append(info)
        visuals=[]
        if SCHEMAS[kind]["image_kind"]:
            pics=db.execute("SELECT visual_id,episode_id,subject_id,kind,"
                "filename,version,sha256 FROM visual_media "
                "WHERE project_id=? AND kind=? ORDER BY created_at DESC LIMIT 500",
                (pid,SCHEMAS[kind]["image_kind"])).fetchall()
            visuals=[dict(x) for x in pics]
        return {"ok":True,"project_id":pid,"episode_id":eid,"kind":kind,
                "fields":{k:{"label":v[0],"type":v[1]}
                          for k,v in SCHEMAS[kind]["fields"].items()},
                "scope":SCHEMAS[kind]["scope"],"image_kind":SCHEMAS[kind]["image_kind"],
                "items":items,"visuals":visuals,"truncated":len(rows)>700,
                "execution_status":"not_connected" if kind=="video_plans" else "planning_only",
                "gpu_action":False}


def get_video_handoff_package(db_path,project_id,episode_id,shot_id):
    """Version-pinned, owner-only export; NEVER a command to execute a GPU job.

    A checksum makes the planning package reproducible across exports. The
    checksum is not a signature or proof of renderer acceptance. Media bytes
    remain in the owner's protected production storage.
    """
    pid=_ident_safe(project_id)
    eid=_ident_safe(episode_id)
    sid=_shot_safe(shot_id)
    with closing(open_db(db_path,initialize=False)) as db:
        if db.execute("SELECT 1 FROM projects WHERE project_id=?",
                      (pid,)).fetchone() is None:
            raise WorkflowError("project_not_found",404)
        episode=db.execute("SELECT episode_id FROM episodes WHERE project_id=? "
            "AND episode_id=?",(pid,eid)).fetchone()
        shot=db.execute("SELECT shot_id,ordinal,duration_ms FROM production_shots "
            "WHERE project_id=? AND episode_id=? AND shot_id=?",
            (pid,eid,sid)).fetchone()
        if episode is None or shot is None:
            raise WorkflowError("shot_not_found",404)
        plan=_record(db,pid,eid,"video_plans",sid)
        if plan is None:raise WorkflowError("video_plan_not_found",404)

        def versioned(row):
            if row is None:return None
            return {"unit_id":row["unit_id"],"revision":row["revision"],
                "status":row["status"],
                "approved_revision":row["approved_revision"],
                "fields":json.loads(row["fields_json"]),
                "source_visual_id":row["source_visual_id"],
                "source_sha256":row["source_sha256"],
                "snapshot_sha256":hashlib.sha256(_snapshot(row).encode()).hexdigest()}

        spec=db.execute("SELECT * FROM studio_work_units WHERE "
            "project_id=? AND episode_id=? AND kind='settings' "
            "AND status='approved' ORDER BY updated_at DESC,unit_id LIMIT 1",
            (pid,eid)).fetchone()
        shot_plan=_record(db,pid,eid,"shot_plans",sid)
        upstream={
            "settings":versioned(spec),
            "shot_plans":versioned(shot_plan),
            "storyboards":versioned(_record(db,pid,eid,"storyboards",sid)),
            "white_models":versioned(_record(db,pid,eid,"white_models",sid))}
        fields=upstream["shot_plans"]["fields"] if shot_plan else {}
        scene_id=fields.get("scene_id")
        scene=None
        if scene_id:
            row=db.execute("SELECT scene_id,revision,approved_revision,status "
                "FROM scene_profiles WHERE project_id=? AND scene_id=?",
                (pid,scene_id)).fetchone()
            if row:
                scene=dict(row)
                approved=db.execute("SELECT visual_id,visual_sha256,"
                    "content_sha256 FROM scene_review_events WHERE "
                    "project_id=? AND scene_id=? AND revision=? AND "
                    "decision='approve' ORDER BY seq DESC LIMIT 1",
                    (pid,scene_id,scene["approved_revision"])).fetchone()
                scene["approved_source"]=dict(approved) if approved else None
        props=[]
        for prop_id in [x.strip() for x in fields.get("prop_ids","").split(",")
                        if x.strip()]:
            props.append({"prop_id":prop_id,
                "version":versioned(_record(db,pid,"","props",prop_id))})
        characters=[]
        rows=db.execute("SELECT character_id,binding_revision,profile_revision,"
            "profile_snapshot,asset_refs_json FROM shot_character_bindings_v2 "
            "WHERE project_id=? AND episode_id=? AND shot_id=? "
            "ORDER BY character_id",(pid,eid,sid)).fetchall()
        for row in rows:
            characters.append({
                "character_id":row["character_id"],
                "binding_revision":row["binding_revision"],
                "profile_revision":row["profile_revision"],
                "profile_snapshot_sha256":hashlib.sha256(
                    row["profile_snapshot"].encode()).hexdigest(),
                "asset_references":json.loads(row["asset_refs_json"])})
        blockers=_video_blockers(db,pid,eid,sid)
        package={"schema":"director_studio_video_handoff_v1",
            "project_id":pid,"episode_id":eid,"shot_id":sid,
            "ordinal":shot["ordinal"],"duration_ms":shot["duration_ms"],
            "video_plan":versioned(plan),"upstream":upstream,
            "scene":scene,"props":props,"character_bindings":characters,
            "blockers":blockers,
            "requires_manual_approval":True,
            "gpu_dispatch_authorized":False,
            "renderer_connected":False}
        canonical=json.dumps(package,sort_keys=True,ensure_ascii=False,
            separators=(",",":")).encode()
        return {"ok":True,"package":package,
            "package_sha256":hashlib.sha256(canonical).hexdigest(),
            "checksum_type":"sha256_canonical_json_not_signature",
            "gpu_action":False}


def get_episode_readiness(db_path,project_id,episode_id):
    """Current per-shot production gates; never claims GPU runner is ready.

    Browser can navigate 31 real shots without pre-creating fake work units.
    All counts come from the same scoped, owner-only SQLite production ledger.
    """
    pid=_ident_safe(project_id)
    eid=_ident_safe(episode_id)
    with closing(open_db(db_path,initialize=False)) as db:
        if db.execute("SELECT 1 FROM projects WHERE project_id=?",
                      (pid,)).fetchone() is None:
            raise WorkflowError("project_not_found",404)
        if db.execute("SELECT 1 FROM episodes WHERE project_id=? "
                      "AND episode_id=?",(pid,eid)).fetchone() is None:
            raise WorkflowError("episode_not_found",404)
        rows=db.execute("SELECT shot_id,ordinal,duration_ms "
            "FROM production_shots WHERE project_id=? AND episode_id=? "
            "ORDER BY ordinal,shot_id LIMIT 701",(pid,eid)).fetchall()
        kinds=("shot_plans","storyboards","white_models","video_plans")
        approved={kind:0 for kind in kinds}
        shots=[]
        prereqs=0
        for row in rows[:700]:
            sid=row["shot_id"]
            stage={}
            for kind in kinds:
                unit=_record(db,pid,eid,kind,sid)
                if unit:
                    stage[kind]={"status":unit["status"],
                        "revision":unit["revision"],
                        "approved_revision":unit["approved_revision"]}
                    if unit["status"]=="approved":
                        approved[kind]+=1
                else:stage[kind]=None
            blockers=_video_blockers(db,pid,eid,sid)
            upstream=[b for b in blockers
                      if b!="video_render_executor_not_connected"]
            if not upstream:prereqs+=1
            shots.append({"shot_id":sid,"ordinal":row["ordinal"],
                "duration_ms":row["duration_ms"],"stages":stage,
                "upstream_blockers":upstream,
                "execution_blocker":"video_render_executor_not_connected",
                "upstream_ready":not upstream,"runner_connected":False})
        return {"ok":True,"project_id":pid,"episode_id":eid,
            "shot_count":len(shots),"total_duration_ms":sum(
                x["duration_ms"] for x in shots),
            "approved_counts":approved,"upstream_ready_count":prereqs,
            "runner_connected":False,"shots":shots,
            "truncated":len(rows)>700,"gpu_action":False}


def list_reviews(db_path,project_id,episode_id=""):
    with closing(open_db(db_path,initialize=False)) as db:
        pid=_ident_safe(project_id)
        # Approval queue includes project-wide assets and selected episode plans.
        # Empty episode means ALL episodes, not only project-level records.
        # An explicit episode also includes shared project-wide assets.
        if episode_id:
            eid=_ident_safe(episode_id)
            if db.execute("SELECT 1 FROM episodes WHERE project_id=? AND "
                          "episode_id=?",(pid,eid)).fetchone() is None:
                raise WorkflowError("episode_not_found",404)
            where="AND (episode_id='' OR episode_id=?) "
            params=(pid,eid)
        else:
            where=""
            params=(pid,)
        rows=db.execute("SELECT project_id,episode_id,kind,unit_id,revision,"
            "fields_json,status,source_visual_id FROM studio_work_units "
            "WHERE project_id=? AND status='in_review' "+where+
            "ORDER BY updated_at DESC LIMIT 300",params).fetchall()
        items=[]
        for row in rows:
            x=dict(row);x["fields"]=json.loads(x.pop("fields_json"))
            items.append(x)
        # Include genuine cross-library pending reviews. The actual approval
        # still runs through each domain's stricter dedicated API.
        scenes=db.execute("SELECT project_id,scene_id,revision,display_name "
            "FROM scene_profiles WHERE project_id=? AND status='in_review' "
            "ORDER BY updated_at DESC LIMIT 150",(pid,)).fetchall()
        for scene in scenes:
            items.append({"project_id":pid,"episode_id":"","kind":"scene",
                "unit_id":scene["scene_id"],"revision":scene["revision"],
                "fields":{"name":scene["display_name"]},"status":"in_review",
                "source_visual_id":None})
        chars=db.execute("SELECT project_id,character_id,item_id,revision,label "
            "FROM character_assets_v2 WHERE project_id=? AND status='in_review' "
            "ORDER BY updated_at DESC LIMIT 150",(pid,)).fetchall()
        for item in chars:
            items.append({"project_id":pid,"episode_id":"","kind":"character_asset",
                "unit_id":item["item_id"],"character_id":item["character_id"],
                "revision":item["revision"],"fields":{"name":item["label"]},
                "status":"in_review","source_visual_id":None})
        return {"ok":True,"pending":items,"total":len(items),"gpu_action":False}
