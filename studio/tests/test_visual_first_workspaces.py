"""Static smoke checks for the visual-first Studio workspaces.

Functional tests separately cover permissions, database writes and review
revisions. These checks are not a substitute for browser screenshot QA.
"""
from html.parser import HTMLParser
from pathlib import Path
import unittest

STUDIO=Path(__file__).resolve().parents[1]


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags={}
        self.attrs={}

    def handle_starttag(self, tag, attrs):
        fields=dict(attrs)
        key=fields.get("id")
        if key:
            self.tags[key]=tag
            self.attrs[key]=fields


class VisualFirstWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(STUDIO/"index.html").read_text(encoding="utf-8")
        cls.js=(STUDIO/"studio.js").read_text(encoding="utf-8")
        cls.css=(STUDIO/"studio.css").read_text(encoding="utf-8")
        cls.doc=Elements()
        cls.doc.feed(cls.html)

    def test_review_is_in_accessible_dialog_not_permanent_third_column(self):
        for stem in ("scene", "character"):
            with self.subTest(stem=stem):
                opener=stem+"InspectorOpen"
                dialog=stem+"InspectorDialog"
                closer=stem+"InspectorClose"
                self.assertEqual(self.doc.tags[dialog], "dialog")
                self.assertEqual(self.doc.tags[opener], "button")
                self.assertEqual(self.doc.attrs[opener]["aria-haspopup"], "dialog")
                self.assertEqual(self.doc.attrs[opener]["aria-controls"], dialog)
                self.assertEqual(self.doc.tags[closer], "button")
                self.assertIn('"'+opener+'"', self.js)
                self.assertIn('"'+dialog+'"', self.js)
                self.assertIn('"'+closer+'"', self.js)
        self.assertIn("dialog.showModal()",self.js)
        self.assertIn("dialog.close()",self.js)
        self.assertIn("sceneInspectorDialog").showModal()',self.js)
        self.assertIn("body[data-page=\"scenes\"] .scene-workspace",self.css)
        self.assertIn("body[data-page=\"characters\"] .character-workspace",self.css)

    def test_scene_category_strip_and_real_asset_drawers(self):
        self.assertEqual(self.doc.tags["sceneCategoryTabs"], "div")
        self.assertEqual(self.doc.tags["sceneMediaDrawer"], "details")
        self.assertEqual(self.doc.tags["characterMediaDrawer"], "details")
        for token in ("sceneCategoryFilter", "filteredVisuals",
                      "visual.reference_type", "aria-pressed"):
            self.assertIn(token,self.js)
        self.assertIn(".scene-category-tab.active",self.css)
        self.assertIn(".studio-media-drawer",self.css)
        self.assertIn("scenePost(\"review\"",self.js)
        self.assertIn('characterPost("approve"',self.js)

if __name__=="__main__":
    unittest.main()
