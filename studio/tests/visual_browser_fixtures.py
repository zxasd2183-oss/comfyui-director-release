"""Offline *visual-test only* API fixtures for the authenticated Studio layout.

None of these SVG sketches or fixture records are installed, served, inserted,
uploaded, approved, or made available in the real Director Studio. They exist
solely to see how the frontend lays out populated grids during browser CI.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse


PID="WaitingOffice"
EP="EP01"
SHOTS=[{
    "shot_id":f"{i:02d}",
    "duration_ms":5200 if i<=30 else 4000,
    "stage":"planned",
} for i in range(1,32)]


def _src(visual_id,kind,subject,name):
    return {"visual_id":visual_id,"kind":kind,"subject_id":subject,
            "episode_id":EP,"filename":name,"version":1,
            "sha256":"visual-fixture-not-production","linked":True,
            "reference_type":"overview"}


def _character(cid,name):
    visual=[_src("FIX_GPT","character",cid,"角色草图.svg")] if cid=="CHAR_GPT" else []
    return {"character_id":cid,"display_name":name,"role":"main",
        "revision":1,"master":None,"visuals":visual,
        "brand_basis":"只参考抽象色彩与秩序，禁止官方 Logo",
        "design_language":"候选草稿，暂未审核",
        "character_notes":"角色素材仍需实际人工审核"}


CHARACTERS=[_character(*p) for p in (
    ("CHAR_GPT","吉皮提"),("CHAR_GEM","杰米奈"),("CHAR_CLA","克劳德"),
    ("CHAR_DS","迪普西克"),("CHAR_ZERO","零"),("CHAR_QWEN","奎文"))]
SCENE_NAMES=[
    ("SCN_OFFICE","事务所 · 内景","interior"),
    ("SCN_EXTERIOR","事务所 · 外观","exterior"),
    ("SCN_CAFE","街角咖啡厅","interior"),
    ("SCN_STREET","城市街道 · 白天","exterior")]
SCENES=[]
for idx,(sid,name,kind) in enumerate(SCENE_NAMES):
    visual=_src("FIX_SCENE_"+str(idx),"scene",sid,"候选场景草图.svg")
    SCENES.append({"project_id":PID,"scene_id":sid,"display_name":name,
        "scene_type":kind,"revision":1,"status":"draft",
        "approved_revision":None,"canonical":None,
        "layout_notes":"采光窗与主要工作台保持相对位置。",
        "lighting_notes":"自然蓝白环境光；实际素材未审批。",
        "camera_rules":"避免跨越主视线轴线。",
        "continuity_rules":"入口、窗户与桌子位置保持一致。",
        "scene_notes":"仅为 CI 视觉排版的示意记录",
        "visuals":[visual],"reviews":[]})


def _record(kind,uid,name,visual_id=None,fields=None):
    value={"name":name} if fields is None else fields
    return {"project_id":PID,"episode_id":"" if kind in ("props","tasks") else EP,
        "kind":kind,"unit_id":uid,"shot_id":uid if kind not in ("props","tasks","settings") else "",
        "revision":1,"status":"draft","approved_revision":None,
        "source_visual_id":visual_id,"note":"仅用于截图排版，不是生产记录",
        "fields":value,"reviews":[]}


PROP_ITEMS=[_record("props",p,n,("FIX_PROP_"+str(i) if i==0 else None),
    {"name":n,"materials":"亚光树脂","dimensions":"标准道具",
     "grip":"左/右手按导演指定"}) for i,(p,n) in enumerate([
    ("PROP_TABLET","平板电脑"),("PROP_COFFEE","咖啡杯"),
    ("PROP_HEADSET","耳机"),("PROP_NOTEBOOK","笔记本")])]
BOARD_ITEMS=[_record("storyboards",f"{i:02d}",f"镜头 SH{i:02d}",
    "FIX_GPT" if i in (1,2) else None,
    {"shot_size":"中近景","composition":"主体居中，视线略偏左",
     "characters":"吉皮提","lighting":"柔和室内侧光"}) for i in (1,2)]
TASK_ITEMS=[_record("tasks",uid,name,None,{
    "title":name,"owner":owner,"priority":priority,
    "workstream":category,"target":"EP01","outcome":""
}) for uid,name,owner,priority,category in [
    ("TASK_CHAR","吉皮提角色母版整理","美术组","P1","角色"),
    ("TASK_SCENE","事务所室内场景构图","场景组","P1","场景"),
    ("TASK_SH01","SH01 分镜图草稿","镜头组","P2","分镜"),
    ("TASK_REVIEW","连续性检查","监审组","P1","审核")]]
FIELDS={
    "props":{"name":"道具名称","materials":"材质","dimensions":"尺寸",
             "grip":"持握规则"},
    "storyboards":{"shot_size":"景别","composition":"画面构图",
                   "characters":"角色","lighting":"光照"},
    "tasks":{"title":"任务名称","owner":"负责人","priority":"优先级",
             "target":"目标"},
    "shot_plans":{"title":"标题","scene_id":"场景","composition":"构图"},
    "white_models":{"stage_width":"场地宽度","stage_depth":"场地深度"},
    "video_plans":{"prompt":"镜头运动","model":"视频工作流"},
    "settings":{"aspect":"画幅","width":"宽度","height":"高度","fps":"帧率"},
}
COUNTS={k:{"total":0,"approved":0} for k in (
    "profile","master","turnaround","face","hair","costume","palette",
    "prop","motion","relationship","continuity","rules")}

SNAPSHOT={
    "sample_age_seconds":1,"dispatch_paused":False,
    "shots":[],"events":[],
    "live":{"gpu_power":{"ok":True,"state":"Stopped"},
            "comfy_queue":{"ok":True,"running":0,"pending":0}},
    "production":{
        "mode":"read_only_production_summary","audit_chain_verified":True,
        "counts":{"projects":1,"episodes":1,"production_shots":31,
                  "assets":0,"findings":0,"exceptions":0},
        "asset_kinds":{},"exception_status":{},
        "projects":[{"project_id":PID,"title":"《待回答事务所》"}],
        "episodes":[{"project_id":PID,"episode_id":EP,"title":"第一集",
                     "stage":"planned"}]}}
EPISODE={
    "ok":True,"project_id":PID,"episode_id":EP,
    "episode":{"stage":"planned"},"shot_count":31,
    "shots":SHOTS,"shots_truncated":False,
    "assets":[],"visual_count":0,"outline":None,
}


def _svg(kind):
    base='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">'
    defs='<defs><linearGradient id="b" x2="0" y2="1"><stop stop-color="#c8edff"/><stop offset="1" stop-color="#ecf9ff"/></linearGradient><linearGradient id="w" x2="0" y2="1"><stop stop-color="#9fd7f2"/><stop offset="1" stop-color="#e8faff"/></linearGradient></defs>'
    if kind=="prop":
        scene='<rect x="0" y="0" width="800" height="500" fill="#e6f6ff"/><ellipse cx="402" cy="431" rx="210" ry="19" fill="#b2d5ea"/><path d="M240 70 605 89 571 403 224 385Z" fill="#3e6683" stroke="#aacadf" stroke-width="14"/><path d="M263 103 580 118 550 358 244 345Z" fill="url(#w)"/><rect x="288" y="148" width="108" height="79" rx="12" fill="#fff"/><rect x="418" y="148" width="108" height="79" rx="12" fill="#e2f6ff"/><rect x="288" y="249" width="237" height="60" rx="12" fill="#c8eafb"/><path d="M311 173h62M439 175h63" stroke="#6eb5da" stroke-width="9"/>'
    elif kind=="character":
        scene='<rect width="800" height="500" fill="#f1faff"/><circle cx="411" cy="241" r="185" fill="#d2edff"/><path d="M188 487Q201 343 306 329L496 329Q602 350 634 487Z" fill="#d6f4f1" stroke="#4a99ad" stroke-width="7"/><path d="M297 292Q254 256 286 143Q311 65 410 64Q512 64 548 162Q565 248 521 311Z" fill="#6a4d43"/><ellipse cx="405" cy="231" rx="113" ry="133" fill="#ffe1d3"/><path d="M299 201Q287 103 374 87Q498 76 523 205Q448 140 396 156Q348 180 299 201Z" fill="#61473f"/><ellipse cx="365" cy="237" rx="14" ry="20" fill="#a46e47"/><ellipse cx="455" cy="237" rx="14" ry="20" fill="#a46e47"/><circle cx="362" cy="233" r="5" fill="#fff"/><circle cx="452" cy="233" r="5" fill="#fff"/><path d="M380 295Q408 315 435 293" stroke="#be877e" stroke-width="6" fill="none"/><path d="M354 356 407 397 457 357" fill="#fff"/><path d="M351 119 478 126" stroke="#553e39" stroke-width="17" opacity=".65"/>'
    else:
        scene='<rect width="800" height="500" fill="#e4f5ff"/><path d="M0 364 155 333 280 362 403 341 600 365 800 330V500H0" fill="#d0e9f6"/><rect x="70" y="50" width="335" height="287" rx="100" fill="url(#w)" stroke="#b3d5e8" stroke-width="17"/><path d="M237 58V341M80 191H398" stroke="#f7fdff" stroke-width="13"/><path d="M95 329 70 475M396 334 436 488" stroke="#a9cbdc" stroke-width="10"/><rect x="420" y="258" width="287" height="85" rx="22" fill="#f9ffff" stroke="#97c6de" stroke-width="7"/><rect x="453" y="230" width="165" height="50" rx="15" fill="#fff"/><path d="M446 338 425 442M684 336 706 440" stroke="#8dafbf" stroke-width="11"/><rect x="490" y="152" width="125" height="75" rx="5" fill="#8dc3df" stroke="#4a88ad" stroke-width="7"/><path d="M550 227V258" stroke="#628daa" stroke-width="10"/><path d="M650 336 650 216" stroke="#78ae8b" stroke-width="8"/><ellipse cx="651" cy="204" rx="36" ry="48" fill="#8fd2a7"/>'
    tag='<rect x="15" y="16" width="260" height="36" rx="8" fill="#ffffffee"/><text x="28" y="39" fill="#3585bd" font-family="sans-serif" font-size="18">VISUAL CI FIXTURE ONLY</text>'
    return base+defs+scene+tag+"</svg>"


def fulfil_fixture(route):
    url=urlparse(route.request.url)
    path=url.path
    query=parse_qs(url.query)
    if path=="/api/v1/production/visual":
        vid=query.get("id",[""])[0]
        kind="character" if "GPT" in vid else "prop" if "PROP" in vid else "scene"
        route.fulfill(status=200,body=_svg(kind),
                      content_type="image/svg+xml")
        return
    if path=="/api/v1/stream":
        route.fulfill(status=200,body="",content_type="text/event-stream")
        return
    if path=="/api/v1/bootstrap":
        result={"csrf":"ci-layout-only","mode":"microsoft_owner"}
    elif path=="/api/v1/snapshot":
        result=SNAPSHOT
    elif path=="/api/v1/production/episode":
        result=EPISODE
    elif path=="/api/v1/characters":
        result={"ok":True,"project_id":PID,"characters":CHARACTERS,
                "available_visuals":[]}
    elif path=="/api/v1/characters/assets":
        result={"ok":True,"project_id":PID,
                "character_id":query.get("character",["CHAR_GPT"])[0],
                "counts":COUNTS,"assets":[],
                "fields":{key:[] for key in COUNTS}}
    elif path=="/api/v1/scenes":
        result={"ok":True,"project_id":PID,"scenes":SCENES,
                "available_visuals":[visual for scene in SCENES
                                     for visual in scene["visuals"]]}
    elif path=="/api/v1/workflow":
        kind=query.get("kind",["tasks"])[0]
        scope="project" if kind in ("props","tasks") else (
            "episode" if kind=="settings" else "shot")
        items={"props":PROP_ITEMS,"tasks":TASK_ITEMS,
               "storyboards":BOARD_ITEMS}.get(kind,[])
        visuals={"props":[_src("FIX_PROP_0","prop","PROP_TABLET","示意道具.svg")],
                 "storyboards":[_src("FIX_GPT","storyboard","01","示意分镜.svg"),
                                _src("FIX_GPT","storyboard","02","示意分镜.svg")]}.get(kind,[])
        result={"ok":True,"project_id":PID,"episode_id":EP if scope!="project" else "",
                "kind":kind,"scope":scope,"image_kind":{
                   "props":"prop","storyboards":"storyboard"}.get(kind),
                "fields":{name:{"label":label,"type":"text"}
                          for name,label in FIELDS.get(kind,{}).items()},
                "items":items,"visuals":visuals}
    elif path=="/api/v1/workflow/reviews":
        result={"ok":True,"total":0,"pending":[]}
    else:
        route.continue_()
        return
    route.fulfill(status=200,body=json.dumps(result,ensure_ascii=False),
                  content_type="application/json")
