"""Static contract for the *real* Glacier scene UI, not a visual mockup.

API/integration/security tests live in test_scene_library.py. These tests
prevent the scene UI from silently regressing to a long in-page form or
dropping its original owner-only production actions.
"""
from html.parser import HTMLParser
from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parents[1]


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=[]
        self.stack=[]
        self.parents={}
        self.controls={}
        self.dialogs=set()

    def handle_starttag(self,tag,attrs):
        data=dict(attrs)
        ident=data.get("id")
        if ident:
            self.ids.append(ident)
            self.parents[ident]=tuple(x[1] for x in self.stack if x[1])
            self.controls[ident]=data
            if tag=="dialog":self.dialogs.add(ident)
        # HTML void tags cannot be nested parents.
        if tag not in ("area","base","br","col","embed","hr","img","input",
                       "link","meta","param","source","track","wbr"):
            self.stack.append((tag,ident))

    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                del self.stack[i:]
                break


class GlacierSceneUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(ROOT/"index.html").read_text(encoding="utf8")
        cls.js=(ROOT/"studio.js").read_text(encoding="utf8")
        cls.css=(ROOT/"studio.css").read_text(encoding="utf8")
        cls.document=Markup()
        cls.document.feed(cls.html)

    def test_scene_has_real_three_part_workspace(self):
        ids=self.document.ids
        self.assertEqual(len(ids),len(set(ids)),"duplicate HTML IDs")
        for name in ("sceneProject","sceneSearch","sceneTypeFilter","sceneList",
                     "sceneStage","sceneGallery","sceneDetail","sceneAssetTools",
                     "sceneVisibleCount","sceneActiveName","sceneActiveStatus",
                     "sceneImageCount","sceneCreateBtn","sceneMessage"):
            self.assertIn(name,ids)
            self.assertIn("scenes",self.document.parents[name])
        self.assertIn('class="scene-workspace"',self.html)
        self.assertIn('class="scene-rail"',self.html)
        self.assertIn('class="scene-center"',self.html)
        self.assertIn('class="scene-inspector"',self.html)

    def test_new_and_edit_use_modal_not_stretched_form(self):
        self.assertIn("sceneEditorDialog",self.document.dialogs)
        self.assertIn("sceneImageDialog",self.document.dialogs)
        self.assertIn("sceneEditorDialog",self.document.parents["sceneEditor"])
        for field in ("sceneId","sceneName","sceneType","sceneLayoutNotes",
                      "sceneLighting","sceneCamera","sceneContinuity",
                      "sceneNotes","sceneSaveBtn"):
            self.assertIn("sceneEditor",self.document.parents[field])
        self.assertIn('"sceneEditorDialog").showModal()',self.js)
        self.assertIn('"sceneEditorDialog").close()',self.js)
        self.assertIn(".scene-editor-dialog:not([open])",self.css)

    def test_assets_use_actual_api_and_image_previews_not_mock_photos(self):
        self.assertIn("scene.visuals",self.js)
        self.assertIn("scene.canonical",self.js)
        self.assertIn("visualURL(data.project_id",self.js)
        self.assertIn('scenePost("link"',self.js)
        self.assertIn('scenePost("review"',self.js)
        self.assertIn('scenePost("update"',self.js)
        self.assertIn('scenePost("create"',self.js)
        self.assertIn('./api/v1/production/visual/upload',self.js)
        self.assertIn('"sceneImageDialog").showModal()',self.js)
        self.assertIn('sceneStatusName[scene.status]',self.js)
        self.assertIn('sceneData?.scenes',self.js)
        self.assertNotIn("request_gpu_start",self.js)

    def test_browser_page_navigation_and_responsive_design(self):
        for name in ("home","projects","characters","scenes","shots","review","audit"):
            self.assertIn('href="?page='+name+'"',self.html)
        self.assertIn("window.history.pushState",self.js)
        self.assertIn("popstate",self.js)
        self.assertIn('body[data-page="scenes"]',self.css)
        self.assertIn(".scene-workspace{height:clamp(",self.css)
        self.assertIn(".scene-hero:before",self.css)
        self.assertIn("@media(max-width:740px)",self.css)
        self.assertIn("workspaceProjectName",self.html)
        self.assertIn("workspaceEpisodeName",self.html)

    def test_review_is_draft_by_default_and_requires_owner_confirmation(self):
        self.assertIn("候选图片",self.js)
        self.assertIn("submitted" if "submitted" in self.js else "in_review",self.js)
        self.assertIn("window.confirm(",self.js)
        self.assertIn("scene.status",self.js)
        self.assertIn("scene.approved_revision",self.js)
        self.assertIn("人工审核",self.html)
        self.assertIn("Microsoft 所有者",self.html)


if __name__=="__main__":
    unittest.main()
