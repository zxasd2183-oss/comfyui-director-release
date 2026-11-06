"""Real-browser Glacier V2 layout smoke test at 1440x900 and mobile.

All project/API responses are intentionally mocked in the browser.
No VPS, Microsoft account, production database, or GPU is contacted.
Screenshots are demonstrative fixtures, not production renders.
"""
import functools
import http.server
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright, expect

STUDIO=Path(__file__).resolve().parents[1]
OUT=STUDIO/"visual-smoke-output"
OUT.mkdir(exist_ok=True)

PROJECT={"project_id":"VisualSmoke","title":"视觉验收模拟项目"}
EPISODE={"project_id":"VisualSmoke","episode_id":"EP01",
         "title":"仅用于界面检查"}
SNAPSHOT={
    "sample_age_seconds":0,"dispatch_paused":True,"events":[],"shots":[],
    "live":{"gpu_power":{"ok":True,"state":"Stopped"},
            "comfy_queue":{"ok":False}},
    "production":{
        "mode":"read_only_production_summary","audit_chain_verified":True,
        "counts":{"projects":1,"episodes":1,"production_shots":31,
                  "assets":0,"findings":0,"exceptions":0},
        "projects":[PROJECT],"episodes":[EPISODE],"asset_kinds":{},
        "audio_asset_count":0,"exception_status":{}
    }
}
SCENE={
    "scene_id":"SCN_HALL","display_name":"事务所大厅 · 演示数据",
    "scene_type":"interior","status":"draft","revision":1,
    "approved_revision":None,"canonical":None,"visuals":[],"reviews":[],
    "layout_notes":"墙面、入口和窗户的相对位置固定。",
    "lighting_notes":"柔和的窗侧光。","camera_rules":"以大厅主轴线布置机位。",
    "continuity_rules":"前台摆设保持一致。","scene_notes":"仅作为 UI 模拟数据。"
}
CHAR={
    "character_id":"CHAR_DEMO","display_name":"示例角色 · 非正式资产",
    "role":"main","revision":1,"master":None,"visuals":[],
    "brand_basis":"仅供视觉验收。","design_language":"原创浅蓝色外观。",
    "character_notes":"这个角色不存在于正式 Studio 数据库。"
}
CATS="profile master turnaround face hair costume palette prop motion relationship continuity rules".split()
ASSETS={
    "project_id":"VisualSmoke","character_id":"CHAR_DEMO","assets":[],
    "counts":{k:{"total":0,"approved":0} for k in CATS}
}

def response(route):
    path=urlparse(route.request.url).path
    if path.endswith("/api/v1/stream"):
        route.abort()
        return
    if path.endswith("/api/v1/bootstrap"):
        result={"csrf":"not-a-real-token","mode":"microsoft_owner"}
    elif path.endswith("/api/v1/snapshot"):
        result=SNAPSHOT
    elif path.endswith("/api/v1/scenes"):
        result={"ok":True,"project_id":"VisualSmoke","scenes":[SCENE],
                "available_visuals":[]}
    elif path.endswith("/api/v1/characters"):
        result={"ok":True,"project_id":"VisualSmoke","characters":[CHAR]}
    elif path.endswith("/api/v1/characters/assets"):
        result=ASSETS
    elif path.endswith("/api/v1/production/episode"):
        result={"ok":True,"shots":[
            {"shot_id":"01","ordinal":1,"duration_ms":3000},
            {"shot_id":"02","ordinal":2,"duration_ms":5000}],
            "assets":[],"episode":EPISODE}
    elif path.endswith("/api/v1/workflow/readiness"):
        blockers=["project_spec_not_approved","shot_plans_not_approved",
                  "storyboards_not_approved","white_models_not_approved"]
        result={"ok":True,"project_id":"VisualSmoke","episode_id":"EP01",
            "shot_count":2,"total_duration_ms":8000,"upstream_ready_count":0,
            "approved_counts":{k:0 for k in (
                "shot_plans","storyboards","white_models","video_plans")},
            "runner_connected":False,"shots":[{
                "shot_id":sid,"ordinal":index+1,"duration_ms":duration,
                "upstream_blockers":blockers,"upstream_ready":False,
                "runner_connected":False,
                "execution_blocker":"video_render_executor_not_connected"}
                for index,(sid,duration) in enumerate([("01",3000),("02",5000)])]}
    elif path.endswith("/api/v1/workflow"):
        kind=parse_qs(urlparse(route.request.url).query).get("kind",[""])[0]
        scope={"tasks":"project","props":"project","settings":"episode"}.get(kind,"shot")
        result={"ok":True,"project_id":"VisualSmoke","episode_id":"EP01",
            "kind":kind,"scope":scope,"fields":{},"items":[],"visuals":[],
            "image_kind":None,"execution_status":"planning_only"}
    else:
        result={"ok":True,"items":[],"shots":[],"tasks":[],"total":0,
                "pending":[],"assets":[],"project_id":"VisualSmoke",
                "episode_id":"EP01"}
    route.fulfill(status=200,content_type="application/json",
                  body=json.dumps(result,ensure_ascii=False))

class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(STUDIO),**kwargs)
    def log_message(self,*args):
        pass

def check_layout(page, name):
    area=page.locator("."+name+"-workspace").bounding_box()
    stage=page.locator("#"+name+"Stage").bounding_box()
    assert area and stage, f"{name}: missing visible workspace/stage"
    assert stage["width"] > area["width"] * .45, (
        f"{name}: visual preview too narrow ({stage['width']:.0f}/"
        f"{area['width']:.0f})")

def main():
    server=http.server.ThreadingHTTPServer(("127.0.0.1",0),QuietHandler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    url=f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={"width":1440,"height":900},
                                  device_scale_factor=1)
            errors=[]
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.route("**/api/v1/**",response)
            page.goto(url,wait_until="load")
            expect(page.locator("body")).to_have_attribute("data-page","home")
            expect(page.locator("#homeProjectTitle")).to_contain_text("视觉验收模拟项目")
            home_cards=page.locator(".icebound-home-progress").bounding_box()
            assert home_cards and home_cards["height"]>=214, (
                "Home dashboard density did not apply at 1440x900")
            page.screenshot(path=str(OUT/"home-1440x900.png"),full_page=True)

            page.locator('a[data-page="scenes"]').click()
            expect(page.locator("body")).to_have_attribute("data-page","scenes")
            expect(page.locator("#sceneActiveName")).to_contain_text("事务所大厅")
            check_layout(page,"scene")
            assert page.locator("#sceneCategoryTabs button").count()==6
            page.screenshot(path=str(OUT/"scenes-1440x900.png"),full_page=True)
            page.locator("#sceneInspectorOpen").click()
            assert page.locator("#sceneInspectorDialog").evaluate("(e)=>e.open")
            expect(page.locator("#sceneDetail")).to_contain_text("固定空间布局")
            page.screenshot(path=str(OUT/"scene-review-dialog-1440x900.png"),
                            full_page=False)
            page.keyboard.press("Escape")
            assert not page.locator("#sceneInspectorDialog").evaluate("(e)=>e.open")
            page.locator("#sceneMediaDrawer summary").click()
            assert page.locator("#sceneMediaDrawer").evaluate("(e)=>e.open")
            page.locator("#sceneCategoryTabs button").nth(2).click()

            page.locator('a[data-page="characters"]').click()
            expect(page.locator("#characterActiveName")).to_contain_text("示例角色")
            check_layout(page,"character")
            expect(page.locator("#characterAssetsPanel")).to_be_visible()
            page.screenshot(path=str(OUT/"characters-1440x900.png"),full_page=True)
            page.locator("#characterInspectorOpen").click()
            assert page.locator("#characterInspectorDialog").evaluate("(e)=>e.open")
            expect(page.locator("#characterDetail")).to_contain_text("人物母版审核")
            page.screenshot(path=str(OUT/"character-review-dialog-1440x900.png"),
                            full_page=False)
            page.locator("#characterInspectorClose").click()
            assert not page.locator("#characterInspectorDialog").evaluate("(e)=>e.open")
            page.locator("#characterMediaDrawer summary").click()
            assert page.locator("#characterMediaDrawer").evaluate("(e)=>e.open")

            page.locator("#characterMediaDrawer summary").click()
            # Exercise ALL seven production workflows with the same owner-only
            # network contract, without creating or approving any real asset.
            for section in ("props","shots","storyboards","white_models",
                            "video_plans","tasks","settings"):
                page.locator('a[data-page="'+section+'"]').click()
                expect(page.locator("body")).to_have_attribute("data-page",section)
                kind={"shots":"shot_plans"}.get(section,section)
                expect(page.locator("#wfStage_"+kind)).to_be_visible()
            expect(page.locator("#wfReadiness_video_plans")).not_to_be_visible()
            page.locator('a[data-page="video_plans"]').click()
            expect(page.locator("#wfReadiness_video_plans")).to_contain_text(
                "2 镜头")
            expect(page.locator(".workflow-readiness-shot")).to_have_count(2)
            page.locator(".workflow-readiness-shot").nth(1).click()
            expect(page.locator("#wfStageTitle_video_plans")).to_contain_text("02")
            page.screenshot(path=str(OUT/"video-readiness-1440x900.png"),
                            full_page=True)

            page.set_viewport_size({"width":390,"height":844})
            page.locator('a[data-page="scenes"]').click()
            page.locator("#sceneMediaDrawer summary").click()
            expect(page.locator("#sceneStage")).to_be_visible()
            page.screenshot(path=str(OUT/"scenes-mobile-390x844.png"),
                            full_page=True)
            assert not errors, "Browser runtime exceptions: "+repr(errors)
            browser.close()
        print("PASS: 1440x900 home/scene/character, review dialogs, seven workflows, video readiness, mobile.")
        print("Screenshots use synthetic UI-only fixtures; they do not show approved production assets.")
    finally:
        server.shutdown()
        server.server_close()

if __name__=="__main__":
    main()
