"""Regression contracts for the actual approved nine-page UI.

CSS presence alone cannot prove pixel-perfect visual parity. The tests protect
real element structure, distinct functional layouts, and owner-only actions.
A browser screenshot against the approved reference remains an independent
release gate and must not be claimed on the strength of these assertions.
"""
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class DOM(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=[]
        self.tags={}
        self.parents={}
        self.stack=[]
    def handle_starttag(self,tag,attrs):
        fields=dict(attrs)
        id_=fields.get("id")
        if id_:
            self.ids.append(id_)
            self.tags[id_]=tag
            self.parents[id_]=[value for _,value in self.stack if value]
        if tag not in ("input","img","br","meta","link","source","hr"):
            self.stack.append((tag,id_))
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                del self.stack[i:];break


class ApprovedDesignLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(ROOT/"index.html").read_text(encoding="utf-8")
        cls.js=(ROOT/"studio.js").read_text(encoding="utf-8")
        cls.css=(ROOT/"studio.css").read_text(encoding="utf-8")
        cls.dom=DOM();cls.dom.feed(cls.html)

    def test_reference_nav_not_fifteen_main_entries(self):
        self.assertIn('class="nav-more-tools"',self.html)
        self.assertIn('data-page="scenes"',self.html)
        self.assertIn('data-page="characters"',self.html)
        self.assertIn('data-page="storyboards"',self.html)
        self.assertIn('nav.closest(".nav-more-tools").open=true',self.js)
        self.assertIn('window.history.pushState',self.js)
        self.assertEqual(len(set(self.dom.ids)),len(self.dom.ids))

    def test_dashboard_matches_compact_four_action_reference_not_old_metric_stack(self):
        self.assertIn('data-action="import"',self.html)
        self.assertIn('data-action="create"',self.html)
        self.assertIn('data-jump="storyboards"',self.html)
        self.assertIn('data-jump="video_plans"',self.html)
        self.assertIn('grid-template-columns:repeat(4,minmax(0,1fr))',self.css)
        self.assertIn('body[data-page="home"] .workspace>.metrics{display:none!important}',self.css)
        self.assertIn('body[data-page="monitor"] .workspace>.metrics{display:grid!important}',self.css)
        self.assertNotIn('42%',self.html)
        self.assertIn('loadHomeEpisodeStats(',self.js)

    def test_scene_is_two_column_large_preview_with_category_tabs(self):
        self.assertIn('id="sceneReferenceTabs"',self.html)
        for label in ("overview","references","lighting","camera","review"):
            self.assertIn('data-scene-tab="'+label+'"',self.html)
        self.assertIn('function applySceneSection()',self.js)
        self.assertIn('row.dataset.sceneSection=name===',self.js)
        self.assertIn('actions.dataset.sceneSection="review"',self.js)
        self.assertIn('link.dataset.sceneSection="references"',self.js)
        self.assertIn('sceneReferenceTabs").querySelectorAll',self.js)
        self.assertIn('grid-template-columns:minmax(255px,29%) minmax(0,1fr)',self.css)
        self.assertIn('grid-area:1/1/3/2',self.css)
        self.assertIn('sceneSection!=="references"',self.js)
        self.assertIn('scenePost("review"',self.js)

    def test_character_has_real_three_view_not_concept_mock_art(self):
        self.assertIn('id="characterTurnaround"',self.html)
        self.assertIn('function renderCharacterTurnaround(profile)',self.js)
        self.assertIn('characterV2Data.assets.filter(a=>a.category==="turnaround"',self.js)
        self.assertIn('a.status==="approved"',self.js)
        self.assertIn('source_visual_id',self.js)
        self.assertIn('characterActiveVisualId',self.js)
        self.assertIn('character-turnaround-grid{display:grid',self.css)
        self.assertIn('characterOpenImage(profile,{',self.js)
        self.assertIn('characterPost("approve"',self.js)

    def test_storyboard_is_viewer_first_with_real_edit_dialog(self):
        self.assertEqual(self.dom.tags.get("wfStoryboardEditDialog"),"dialog")
        self.assertIn('wfStoryboardEditorMount',self.dom.ids)
        self.assertIn('id="storyboardTimeline"',self.html)
        self.assertIn('class="storyboard-shot-summary"',self.js)
        self.assertIn('const detail=kind==="storyboards"?',self.js)
        self.assertIn('wfStoryboardEditDialog").showModal()',self.js)
        self.assertIn('wfStoryboardEditDialog").close()',self.js)
        self.assertIn('["时长",shot?',self.js)
        self.assertIn('state.shots.reduce(',self.js)
        self.assertIn('workflowPost("save"',self.js)
        self.assertIn('workflowPost("review"',self.js)
        self.assertIn('.workflow-editor-dialog:not([open])',self.css)

    def test_distinct_real_prop_task_video_and_settings_layouts(self):
        for name in ("props","tasks","video_plans","settings"):
            self.assertIn('body[data-page="'+name+'"] .workflow-grid',self.css)
        self.assertIn('icebound-prop-thumb',self.js)
        self.assertIn('icebound-task-table-head',self.js)
        self.assertIn('渲染前置条件核对',self.js)
        self.assertIn('video_render_executor_not_connected',self.js)
        self.assertNotIn('request_gpu_start(',self.js)


if __name__=="__main__":
    unittest.main()
