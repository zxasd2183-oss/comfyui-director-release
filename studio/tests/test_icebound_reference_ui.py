"""Icebound V2 approval-reference UI contracts, with genuine project data.

These tests prevent returning to a stretched management form or shipping
fake production art / unverified shot progress as approved data.
"""
import html.parser
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class Ids(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=[]
    def handle_starttag(self,tag,attrs):
        value=dict(attrs).get("id")
        if value:self.ids.append(value)


class IceboundReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(ROOT/"index.html").read_text(encoding="utf-8")
        cls.js=(ROOT/"studio.js").read_text(encoding="utf-8")
        cls.css=(ROOT/"studio.css").read_text(encoding="utf-8")
        cls.server=(ROOT/"studio_server.py").read_text(encoding="utf-8")

    def test_exact_approval_reference_common_shell(self):
        for component in ("workspaceProjectName","workspaceProjectEnglish",
                          "workspaceEpisodeName","workspaceEpisodeSummary",
                          "headerStudioStatus","headerGpuStatus",
                          "headerAuditStatus"):
            self.assertIn('id="'+component+'"',self.html)
            self.assertIn('"'+component+'"',self.js)
        self.assertIn("冰川版 V2",self.html)
        self.assertIn('url("./glacier-peaks.svg")',self.css)
        self.assertIn('url("./glacier-banner.svg")',self.css)
        self.assertIn('if path in ("/glacier-peaks.svg", "/glacier-banner.svg")',
                      self.server)
        for name in ("glacier-peaks.svg","glacier-banner.svg"):
            data=(ROOT/name).read_text(encoding="utf-8")
            self.assertIn('xmlns="http://www.w3.org/2000/svg"',data)

    def test_reference_home_has_real_project_and_task_cards(self):
        for ident in ("homeProjectTitle","homeEpisodeLine","homeProgressRing",
                      "homeProgressValue","homeRecentTasks"):
            self.assertIn('id="'+ident+'"',self.html)
        for route in ("projects","storyboards","video_plans"):
            self.assertIn('data-jump="'+route+'"',self.html)
        self.assertIn('data-action="create"',self.html)
        self.assertIn('data-action="import"',self.html)
        self.assertIn('loadHomeEpisodeStats(',self.js)
        self.assertIn('loadHomeRecentTasks(',self.js)
        self.assertIn('production/episode?project=',self.js)
        self.assertIn('kind:"tasks"',self.js)
        self.assertIn('data.shots',self.js)
        self.assertNotIn('42%',self.html)
        self.assertIn('home"] .workspace>.icebound-quick-actions{display:grid}',self.css)
        self.assertIn('.workspace>.icebound-quick-actions,.workspace>.icebound-home-overview{display:none}',self.css)

    def test_storyboard_has_actual_31_shot_slot_support(self):
        for ident in ("storyboardTimeline","storyboardTimelineCount",
                      "wfStage_storyboards","wfList_storyboards"):
            self.assertIn('id="'+ident+'"',self.html)
        for action in ("frames","list","bindings","versions","continuity"):
            self.assertIn('data-storyboard-action="'+action+'"',self.html)
        self.assertIn('function workflowRenderStoryboardTimeline()',self.js)
        self.assertIn('state.shots.map(shot=>',self.js)
        self.assertIn('state.shots.reduce(',self.js)
        self.assertIn('record?"V"+record.revision:"尚未建档"',self.js)
        self.assertIn('state.shots[0]?.shot_id',self.js)
        self.assertIn('body[data-page="storyboards"] .workflow-grid',self.css)

    def test_scene_gallery_and_route_are_isolated(self):
        self.assertIn('body[data-page="scenes"] .scene-list{display:grid',self.css)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))',self.css)
        for name in ("characters","scenes","props","shots","storyboards",
                     "white_models","video_plans","review","tasks","settings"):
            self.assertIn('href="?page='+name+'"',self.html)
        self.assertIn('window.history.pushState',self.js)

    def test_all_dom_ids_unique_and_no_gpu_execution_buttons(self):
        parser=Ids()
        parser.feed(self.html)
        self.assertEqual(len(parser.ids),len(set(parser.ids)))
        self.assertNotIn('request_gpu_start(',self.js)
        self.assertNotIn('rendered_at:"now"',self.js)


if __name__=="__main__":
    unittest.main()
