"""Real-browser Glacier V2 layout smoke test at 1440x900 and mobile.

All project/API responses are intentionally mocked in the browser.
No VPS, Microsoft account, production database, or GPU is contacted.
Screenshots are demonstrative fixtures, not production renders.
"""
import base64
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import tempfile
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

BATCH_CLIPS={}
BATCH_ENTRIES=[]
for sid in ("01","02"):
    content=bytes((0,0,0,24))+b"ftypisom"+bytes([int(sid)])*300
    digest=hashlib.sha256(content).hexdigest()
    filename=f"SH_{sid}_{digest[:16]}.mp4"
    BATCH_CLIPS[filename]=content
    BATCH_ENTRIES.append({"shot_id":sid,"filename":filename,
        "file_sha256":digest,"size_bytes":len(content),
        "plan_revision":1,
        "package_sha256":hashlib.sha256(sid.encode()).hexdigest(),
        "prompt_id":"comfy_fixture_"+sid})
BATCH_INVENTORY={"schema":"director_studio_video_delivery_v1",
    "project_id":"VisualSmoke","episode_id":"EP01","shot_count":2,
    "shots":BATCH_ENTRIES,"episode_bundle_sha256":"c"*64,
    "requires_owner_upload":True,
    "automatically_uploaded":False,"gpu_dispatch_authorized":False}
BATCH_DOCUMENT={"ok":True,"manifest":BATCH_INVENTORY,
    "checksum_type":"sha256_canonical_json_not_signature",
    "manifest_sha256":hashlib.sha256(json.dumps(BATCH_INVENTORY,
        sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()}
BATCH_POST_EVENTS=[]
PICTURE_MOCK={"existing":True,"queued":False}
AUDIO_EVENTS=[]
AUDIO_TRACKS=[{"stem":"music","revision":1,"audio_id":"AUD_"+"a"*32,
    "sha256":"e"*64,"status":"in_review","source_current":True,
    "duration_seconds":8.0,"review_reason":None,"reviewer":None}]


def response(route):
    path=urlparse(route.request.url).path
    if path.endswith("/api/v1/stream"):
        route.abort()
        return
    if route.request.method=="POST" and path.startswith("/api/v1/audio-stems/"):
        action=path.rsplit("/",1)[-1]
        payload=route.request.post_data_json
        AUDIO_EVENTS.append(action)
        if action=="start":
            result={"ok":True,"upload_id":"AUP_"+"b"*32,
                "received_bytes":0,"size_bytes":payload["size_bytes"]}
        elif action=="chunk":
            result={"ok":True,"received_bytes":payload["offset"]+
                len(base64.b64decode(payload["chunk_base64"]))}
        elif action=="finish":
            result={"ok":True,"audio_id":"AUD_"+"b"*32,"revision":1,
                "status":"in_review"}
            AUDIO_TRACKS.append({"stem":"effects","revision":1,
                "audio_id":result["audio_id"],"sha256":"f"*64,
                "status":"in_review","source_current":True,
                "duration_seconds":8.0,"review_reason":None,"reviewer":None})
        elif action=="review":
            for item in AUDIO_TRACKS:
                if item["audio_id"]==payload["audio_id"]:
                    item["status"]="approved" if payload["decision"]=="approve" else "rejected"
            result={"ok":True,"status":payload["decision"]}
        route.fulfill(status=200,content_type="application/json",
                      body=json.dumps(result))
        return
    if route.request.method=="POST" and path.endswith("/api/v1/picture-cuts/assemble"):
        PICTURE_MOCK["queued"]=True
        route.fulfill(status=202,content_type="application/json",body=json.dumps({
            "ok":True,"job_id":"PCJOB_"+"a"*32,"status":"queued",
            "gpu_action":False}))
        return
    if route.request.method=="POST" and path.startswith("/api/v1/video-results/"):
        event=path.rsplit("/",1)[-1]
        payload=route.request.post_data_json
        BATCH_POST_EVENTS.append(event)
        if event=="start":
            result={"ok":True,"upload_id":"UP_"+"a"*32,
                "received_bytes":0,"size_bytes":payload["size_bytes"]}
            if payload["shot_id"]=="02":
                result={"ok":True,"already_imported":True,
                    "take_id":"TAKE_"+"b"*32,
                    "received_bytes":payload["size_bytes"],
                    "size_bytes":payload["size_bytes"]}
        elif event=="chunk":
            result={"ok":True,"received_bytes":payload["offset"]+
                len(base64.b64decode(payload["chunk_base64"]))}
        elif event=="finish":
            result={"ok":True,"status":"in_review","take_id":"TAKE_"+"a"*32}
        else:
            result={"ok":True}
        route.fulfill(status=200,content_type="application/json",
                      body=json.dumps(result))
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
    elif path.endswith("/api/v1/audio-stems"):
        result={"ok":True,"project_id":"VisualSmoke","episode_id":"EP01",
            "tracks":AUDIO_TRACKS,"gpu_action":False}
    elif path.endswith("/api/v1/picture-cuts/readiness"):
        result={"ok":True,"project_id":"VisualSmoke","episode_id":"EP01",
            "shot_count":2,"approved_count":2,"total_duration_ms":8000,
            "ready":True,"blocked":[],"source_manifest_sha256":"d"*64}
    elif path.endswith("/api/v1/picture-cuts/jobs"):
        result={"ok":True,"jobs":[{
            "job_id":"PCJOB_"+"a"*32,"status":"queued","error_code":None}]
            if PICTURE_MOCK["queued"] else [],"gpu_action":False}
    elif path.endswith("/api/v1/picture-cuts"):
        result={"ok":True,"picture_cuts":[{
            "cut_id":"CUT_"+"a"*32,"source_current":True,
            "source_manifest_sha256":"d"*64,"file_sha256":"e"*64,
            "size_bytes":88888,"duration_seconds":8.0,"status":"in_review",
            "review_reason":None,"reviewer":None}]
            if PICTURE_MOCK["existing"] else [],
            "final_audio_mixed":False,"gpu_action":False}
    elif path.endswith("/api/v1/video-results"):
        result={"ok":True,"project_id":"VisualSmoke","episode_id":"EP01",
            "shot_id":"01","takes":[{
                "take_id":"TAKE_"+"a"*32,"sha256":"b"*64,
                "size_bytes":1024000,"width":1080,"height":1920,
                "fps":24.0,"duration_seconds":3.0,"codec":"h264",
                "status":"in_review","plan_revision":1,
                "source_current":True,
                "review_reason":None,"reviewer":None,
                "prompt_id":"fixture-prompt"}]}
    elif path.endswith("/api/v1/workflow/reviews"):
        result={"ok":True,"total":1,"pending":[{
            "project_id":"VisualSmoke","episode_id":"EP01",
            "kind":"video_take","unit_id":"TAKE_"+"a"*32,
            "shot_id":"01","revision":1,"fields":{"name":"SH01 已回传视频"},
            "status":"in_review","source_visual_id":None}]}
    elif path.endswith("/api/v1/workflow/video-packages"):
        result={"ok":True,"bundle_sha256":"c"*64,
            "bundle":{"all_ready":True,"shot_count":2,
                "shot_ids":["01","02"],"packages":[{
                    "package":{"shot_id":entry["shot_id"],
                        "video_plan":{"revision":1,"status":"in_review"}},
                    "package_sha256":entry["package_sha256"]}
                    for entry in BATCH_ENTRIES]}}
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
        sample=[{"unit_id":"01","episode_id":"EP01","revision":1,
            "status":"in_review","fields":{"model":"H3","prompt":"模拟运动"},
            "note":"","source_visual_id":None,"approved_revision":None,
            "blockers":["video_render_executor_not_connected"]}] if (
                kind=="video_plans") else []
        result={"ok":True,"project_id":"VisualSmoke","episode_id":"EP01",
            "kind":kind,"scope":scope,"fields":{},"items":sample,"visuals":[],
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
    fixture=tempfile.TemporaryDirectory()
    folder=Path(fixture.name)/"StudioGpuDelivery"
    folder.mkdir()
    (folder/"manifest.json").write_text(json.dumps(
        BATCH_DOCUMENT,ensure_ascii=False),encoding="utf-8")
    for filename,content in BATCH_CLIPS.items():
        (folder/filename).write_bytes(content)
    wav=Path(fixture.name)/"studio-test-effects.wav"
    wav.write_bytes(b"RIFF"+bytes(8)+b"WAVE"+bytes(500))
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
            page.locator('a[data-page="review"]').click()
            expect(page.locator("#wfReviewList")).to_contain_text("真实视频成片")
            page.locator("#wfReviewList button").first.click()
            expect(page.locator("body")).to_have_attribute("data-page","video_plans")
            expect(page.locator("#wfVideoTakes_video_plans .video-take-player")).to_have_count(1)
            expect(page.locator("#wfVideoTakes_video_plans .video-review-reason")).to_have_count(1)
            expect(page.locator("#wfPictureCuts_video_plans")).to_contain_text("整集画面初剪")
            expect(page.locator("#wfPictureCuts_video_plans .video-take-player")).to_have_count(1)
            expect(page.locator("#wfPictureCuts_video_plans .video-review-reason")).to_have_count(1)
            page.screenshot(path=str(OUT/"real-video-review-ui-1440x900.png"),
                            full_page=True)
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
            expect(page.locator("#wfBatchReturnFiles_video_plans")).to_be_visible()
            expect(page.locator("#wfBatchReturnSubmit_video_plans")).to_be_visible()
            page.locator("#wfBatchReturnFiles_video_plans").set_input_files(str(folder))
            page.locator("#wfBatchReturnSubmit_video_plans").click()
            expect(page.locator("#wfBatchReturnMessage_video_plans")).to_contain_text(
                "回传完成：2/2")
            assert BATCH_POST_EVENTS.count("start")==2
            assert BATCH_POST_EVENTS.count("chunk")==1
            assert BATCH_POST_EVENTS.count("finish")==1
            expect(page.locator("#wfAudioStems_video_plans")).to_contain_text(
                "独立声音制作")
            page.locator('#wfAudioStems_video_plans input[type="file"]').set_input_files(
                str(wav))
            page.locator('#wfAudioStems_video_plans select').select_option("effects")
            page.locator('#wfAudioStems_video_plans .video-upload-form textarea').fill(
                "TEST-EFFECTS-LICENSE-001 operator checked rights file")
            page.get_by_role("button",name="上传整集 WAV 轨道").click()
            expect(page.locator("#wfAudioStems_video_plans")).to_contain_text(
                "音效 / 环境声")
            assert AUDIO_EVENTS.count("start")==1
            assert AUDIO_EVENTS.count("chunk")==1
            assert AUDIO_EVENTS.count("finish")==1
            page.locator('#wfAudioStems_video_plans .audio-rights-verified input').first.check()
            page.locator('#wfAudioStems_video_plans .video-review-reason').first.fill(
                "已审查音乐轨版权和同步质量，确认拥有许可凭证且同意使用。")
            page.once("dialog",lambda dialog:dialog.accept())
            page.get_by_role("button",name="核准此轨及权利").first.click()
            expect(page.locator("#wfAudioStems_video_plans")).to_contain_text("批准")
            assert AUDIO_EVENTS.count("review")==1
            PICTURE_MOCK["existing"]=False
            page.locator('a[data-page="tasks"]').click()
            page.locator('a[data-page="video_plans"]').click()
            cut_start=page.get_by_role("button",
                name="一键生成整集画面初剪（本地 CPU）")
            expect(cut_start).to_be_visible()
            page.once("dialog",lambda dialog:dialog.accept())
            cut_start.click()
            expect(page.locator("#wfPictureCuts_video_plans")).to_contain_text(
                "已排队")
            assert PICTURE_MOCK["queued"]
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
        fixture.cleanup()

if __name__=="__main__":
    main()
