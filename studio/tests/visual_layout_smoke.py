"""Chromium empty-state layout regression for the *real* Studio HTML/CSS.

No credential bypass and no invented production images. The browser serves
the exact checked-out static Studio files and manually selects page routes.
These screenshots prove CSS geometry only, NOT authenticated runtime API
success or pixel-perfect matching to the user's approved reference.
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import threading

from playwright.sync_api import sync_playwright
from visual_browser_fixtures import fulfil_fixture

ROOT=Path(__file__).resolve().parents[1]
PAGES=("home","characters","scenes","props","shots",
       "storyboards","white_models","video_plans","review",
       "tasks","settings")
MOBILE_PAGES=("home","characters","scenes","storyboards","props")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*_args):
        pass


def bounds(page,selector):
    value=page.locator(selector).bounding_box()
    if not value:
        raise AssertionError(f"No visible bounds for {selector!r}")
    return value


def check_desktop(page,name):
    stage=page.locator("[data-page='"+name+"']").count()
    if stage==0:
        # body has a dynamic data-page attribute; check the intended page.
        assert page.locator("body").get_attribute("data-page")==name
    if name=="home":
        assert page.locator(".icebound-quick-actions button").count()==4
        assert page.locator(".icebound-quick-actions").is_visible()
        assert not page.locator(".workspace > .metrics").is_visible()
        assert not page.locator("#scenes").is_visible()
        return
    if name=="scenes":
        rail=bounds(page,"#scenes .scene-rail")
        center=bounds(page,"#scenes .scene-center")
        lower=bounds(page,"#scenes .scene-inspector")
        assert rail["x"]+rail["width"] <= center["x"]+5, (rail,center)
        assert lower["y"] >= center["y"]+center["height"]-5, (lower,center)
        assert abs(lower["x"]-center["x"])<7, (lower,center)
        assert page.locator("#sceneReferenceTabs button").count()==5
        assert lower["y"]+lower["height"]<=905,(lower,"scene inspector outside first viewport")
        return
    if name=="characters":
        rail=bounds(page,"#characters .character-rail")
        center=bounds(page,"#characters .character-center")
        side=bounds(page,"#characters .character-inspector")
        assert rail["x"]<center["x"]<side["x"]
        assert page.locator("#characterTurnaround").is_visible()
        assert side["y"]+side["height"]<=905,(side,"character inspector outside first viewport")
        return
    if name=="storyboards":
        rail=bounds(page,"#workflow_storyboards .workflow-rail")
        canvas=bounds(page,"#workflow_storyboards .workflow-stage-wrap")
        inspector=bounds(page,"#workflow_storyboards .workflow-inspector")
        assert rail["x"]<canvas["x"]<inspector["x"]
        timeline=bounds(page,"#storyboardTimeline")
        assert timeline["y"]+timeline["height"]<=905,(timeline,"storyboard timeline below first viewport")
        assert not page.locator("#wfStoryboardEditDialog").is_visible()
        return
    if name in ("props","video_plans"):
        rail=bounds(page,"#workflow_"+name+" .workflow-rail")
        canvas=bounds(page,"#workflow_"+name+" .workflow-stage-wrap")
        editor=bounds(page,"#workflow_"+name+" .workflow-inspector")
        assert rail["x"]+rail["width"]<canvas["x"]+6
        assert editor["y"]>=canvas["y"]+canvas["height"]-5
        assert editor["y"]+editor["height"]<=905,(name,"work inspector below first viewport")
        return
    if name=="tasks":
        assert not page.locator("#workflow_tasks .workflow-stage-wrap").is_visible()
        assert page.locator("#wfList_tasks").is_visible()
        return
    if name=="settings":
        assert not page.locator("#workflow_settings .workflow-stage-wrap").is_visible()
        assert page.locator("#wfDetail_settings").is_visible()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default="studio-layout-shots")
    args=parser.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    handler=partial(QuietHandler,directory=str(ROOT))
    server=ThreadingHTTPServer(("127.0.0.1",0),handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    url=f"http://127.0.0.1:{server.server_port}/index.html"
    try:
        with sync_playwright() as playwright:
            chromium=shutil.which("chromium") or shutil.which("google-chrome")
            opts={"headless":True,"args":["--no-sandbox"]}
            if chromium:opts["executable_path"]=chromium
            browser=playwright.chromium.launch(**opts)
            try:
                desktop=browser.new_page(viewport={"width":1440,"height":900},
                                         device_scale_factor=1)
                for name in PAGES:
                    desktop.goto(url,wait_until="domcontentloaded")
                    desktop.evaluate("(name)=>document.body.dataset.page=name",name)
                    desktop.wait_for_timeout(100)
                    check_desktop(desktop,name)
                    desktop.screenshot(path=str(out/f"desktop_{name}.png"))
                mobile=browser.new_page(viewport={"width":390,"height":844},
                                        device_scale_factor=1)
                for name in MOBILE_PAGES:
                    mobile.goto(url,wait_until="domcontentloaded")
                    mobile.evaluate("(name)=>document.body.dataset.page=name",name)
                    mobile.wait_for_timeout(80)
                    assert mobile.locator(".workspace").is_visible()
                    assert mobile.locator("body").evaluate(
                        "el=>el.scrollWidth")<=395, name
                    mobile.screenshot(path=str(out/f"mobile_{name}.png"),
                                      full_page=True)

                # Separate illustrative CI fixtures exercise populated layouts.
                # Nothing is written to the production database; SVGs contain an
                # explicit "VISUAL CI FIXTURE ONLY" watermark.
                cases=[
                    ("home",".icebound-progress-row",4),
                    ("characters","#characterList .character-entry",6),
                    ("scenes","#sceneList .scene-entry",4),
                    ("props","#wfList_props .workflow-record",4),
                    ("storyboards","#storyboardTimeline .icebound-timeline-card",31),
                    ("tasks","#wfList_tasks .workflow-record",4),
                ]
                fixture=browser.new_page(viewport={"width":1440,"height":900},
                                         device_scale_factor=1)
                fixture.route("**/api/v1/**",fulfil_fixture)
                fixture_errors=[]
                fixture.on("pageerror",lambda e:fixture_errors.append(str(e)))
                for name,selector,expected in cases:
                    fixture.goto(url+"?page="+name,wait_until="domcontentloaded")
                    try:
                        fixture.wait_for_function("""([selector,expected]) =>
                          document.querySelectorAll(selector).length>=expected""",
                          arg=[selector,expected],timeout=8000)
                    finally:
                        fixture.screenshot(path=str(out/f"fixture_{name}.png"))
                    count=fixture.locator(selector).count()
                    assert count>=expected,(name,count,expected)
                assert not fixture_errors,fixture_errors
                print("Fixture visual smoke passed: 6 populated desktop screenshots")

                print("Visual layout smoke passed: 11 desktop + 5 mobile screenshots")
            finally:
                browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=="__main__":
    main()
