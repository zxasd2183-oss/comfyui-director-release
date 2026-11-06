"""Protect the functional Glacier character page, not merely a concept mockup."""
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class Page(HTMLParser):
    VOID={"input","img","link","meta","br","hr","source","area","base"}
    def __init__(self):
        super().__init__();self.ids=[];self.ancestors={};self.tags={};self.stack=[]
    def handle_starttag(self,tag,attrs):
        fields=dict(attrs);key=fields.get("id")
        if key:
            self.ids.append(key)
            self.ancestors[key]=tuple(k for t,k in self.stack if k)
            self.tags[key]=tag
        if tag not in self.VOID:self.stack.append((tag,key))
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                del self.stack[i:];break

class GlacierCharactersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(ROOT/"index.html").read_text(encoding="utf8")
        cls.js=(ROOT/"studio.js").read_text(encoding="utf8")
        cls.css=(ROOT/"studio.css").read_text(encoding="utf8")
        cls.doc=Page();cls.doc.feed(cls.html)

    def test_all_controls_unique_and_in_correct_real_workspaces(self):
        self.assertEqual(len(self.doc.ids),len(set(self.doc.ids)),
            "duplicate ID breaks real event binding")
        for k in ("characterProject","characterSearch","characterRoleFilter",
                  "characterList","characterVisibleCount","characterStage",
                  "characterVisualGallery","characterReferenceTools",
                  "characterAssetsPanel","characterDetail","characterCreateBtn",
                  "characterCount","characterActiveStatus","characterVisualCount"):
            with self.subTest(control=k):
                self.assertIn(k,self.doc.ids)
                self.assertIn("characters",self.doc.ancestors[k])
        self.assertIn('class="character-rail"',self.html)
        self.assertIn('class="character-center"',self.html)
        self.assertIn('class="character-inspector"',self.html)

    def test_real_dialogs_not_page_long_forms(self):
        for k in ("characterEditorDialog","characterAssetEditorDialog",
                  "characterImageDialog"):
            self.assertEqual(self.doc.tags[k],"dialog")
        self.assertIn("characterEditorDialog",self.doc.ancestors["characterEditForm"])
        self.assertIn("characterAssetEditorDialog",
                      self.doc.ancestors["characterAssetEditorMount"])
        self.assertIn('characterEditorDialog").showModal()',self.js)
        self.assertIn('characterAssetEditorDialog");',self.js)
        self.assertIn('dialog.showModal();',self.js)
        self.assertIn('characterImageDialog").showModal()',self.js)
        self.assertIn(".character-editor-dialog:not([open])",self.css)

    def test_visuals_real_images_not_illustrative_fake_results(self):
        for token in ('visualURL(data.project_id','c.visuals',
                      'c.master?.visual_id','characterActiveVisualId',
                      'characterStage','characterVisualGallery',
                      'characterOpenImage'):
            self.assertIn(token,self.js)
        self.assertIn("候选素材 · 尚未批准",self.js)
        self.assertIn("暂无角色参考图",self.js)
        self.assertIn("角色库",self.html)

    def test_existing_operations_connected_and_review_secure(self):
        for snippet in ('characterPost("create"','characterPost("update"',
                        'characterPost("link"','characterPost("approve"',
                        'characterPost("assets/create"',
                        'characterPost("assets/revise"',
                        'characterPost("assets/review"',
                        './api/v1/production/visual/upload',
                        'kind:"character"', 'window.confirm(', 'microsoftOwner'):
            self.assertIn(snippet,self.js)
        self.assertIn("picked.subject_id===c.character_id",self.js)
        self.assertIn("character_individual_visual_required",
            (ROOT/"character_library.py").read_text(encoding="utf8"))
        self.assertNotIn("request_gpu_start",self.js)

    def test_glacier_and_responsive_layout(self):
        for selector in (".character-hero{",".character-workspace{",
                         ".character-main-image{",".character-visual-tile{",
                         ".character-v2-tabs{",".character-main-review{",
                         ".character-editor-dialog{",
                         "@media(max-width:740px)"):
            self.assertIn(selector,self.css)
        for page in ("characters","scenes"):
            self.assertIn('href="?page='+page+'"',self.html)
        self.assertIn('body[data-page="characters"]',self.css)

if __name__=="__main__":
    unittest.main()
