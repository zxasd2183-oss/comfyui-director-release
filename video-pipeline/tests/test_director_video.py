import copy
import csv
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import director_video as dv


class VideoPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.workflow = {
            "6": {"class_type": "TextNode", "inputs": {"text": "placeholder"}},
            "9": {"class_type": "FrameNode", "inputs": {"frames": 24, "seed": 7}},
            "12": {"class_type": "OutputNode", "inputs": {"from": ["9", 0]}}
        }
        self.binding = {"prompt": {"node": "6", "input": "text"},
                        "frames": {"node": "9", "input": "frames"},
                        "seed": {"node": "9", "input": "seed"}}
        self.shots = [{"shot_id": "01", "seconds": 5, "prompt": "Camera slowly pans"},
                      {"shot_id": "02", "seconds": 3, "prompt": "Character smiles"}]

    def plan(self):
        return dv.build_plan(self.workflow, self.binding, self.shots, fps=24)

    def test_valid_api_workflow_and_no_mutation(self):
        original = copy.deepcopy(self.workflow)
        plan = self.plan()
        self.assertEqual(plan["shot_count"], 2)
        self.assertEqual(plan["total_seconds"], 8)
        self.assertEqual(plan["jobs"][0]["frames"], 120)
        self.assertEqual(plan["jobs"][0]["graph"]["6"]["inputs"]["text"], "Camera slowly pans")
        self.assertEqual(plan["jobs"][1]["graph"]["9"]["inputs"]["frames"], 72)
        self.assertEqual(original, self.workflow)

    def test_ui_graph_must_be_exported(self):
        with self.assertRaisesRegex(dv.PlanError, "Export Workflow"):
            dv.validate_workflow({"nodes": [{"id": 1}], "links": []})

    def test_broken_binding_fails_closed(self):
        with self.assertRaisesRegex(dv.PlanError, "does not exist"):
            dv.validate_bindings({"prompt": {"node": "404", "input": "text"}}, self.workflow)
        with self.assertRaisesRegex(dv.PlanError, "literal input"):
            dv.validate_bindings({"prompt": {"node": "12", "input": "from"}}, self.workflow)

    def test_csv_chinese_shot_table_and_markdown_prompts(self):
        path = self.root / "shots.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["镜号", "时长秒", "画面与动作"])
            w.writeheader()
            w.writerow({"镜号": "1", "时长秒": "3", "画面与动作": "拍桌"})
            w.writerow({"镜号": "2", "时长秒": "5", "画面与动作": "举手"})
        notes = self.root / "notes.md"
        notes.write_text("### 镜头 01｜00:00–00:03\n"
                         "- **主镜头提示：**掌心和桌面，纸页微微弹起。\n"
                         "### 镜头 02｜00:03–00:08\n"
                         "- **主镜头提示：**角色站起，向镜头微笑。\n", encoding="utf-8")
        shots = dv.load_shots(path, dv.load_prompt_notes(notes))
        self.assertEqual([x["shot_id"] for x in shots], ["01", "02"])
        self.assertIn("纸页", shots[0]["prompt"])
        self.assertEqual(sum(x["seconds"] for x in shots), 8)

    def test_duplicate_invalid_duration_or_missing_prompt_rejected(self):
        with self.assertRaisesRegex(dv.PlanError, "unique"):
            dv.load_shots(self._json_file([self.shots[0], self.shots[0]]))
        with self.assertRaisesRegex(dv.PlanError, "between"):
            dv.load_shots(self._json_file([{"id": "bad", "seconds": 300, "prompt": "clip"}]))
        with self.assertRaisesRegex(dv.PlanError, "nonempty prompt"):
            dv.load_shots(self._json_file([{"id": 2, "seconds": 5, "prompt": ""}]))

    def test_plan_digest_prevents_mismatched_resume(self):
        plan = self.plan()
        db = self.root / "state.sqlite"
        con = dv.db_open(db, plan)
        dv.set_state(con, "01", "queued", prompt_id="12345678-1234")
        con.close()
        again = dv.db_open(db, plan)
        self.assertEqual(
            again.execute("SELECT state FROM runs WHERE shot_id='01'").fetchone()[0], "queued")
        again.close()
        changed = copy.deepcopy(plan)
        changed["jobs"][0]["graph"]["6"]["inputs"]["text"] = "different"
        with self.assertRaisesRegex(dv.PlanError, "NEW database"):
            dv.db_open(db, changed)

    def test_submit_requires_explicit_double_opt_in(self):
        plan = self.root / "plan.json"
        dv.atomic_json(plan, self.plan())
        state = self.root / "state.sqlite"
        with patch.object(dv, "comfy_json") as network:
            self.assertEqual(dv.run_cli(["submit", "--plan", str(plan), "--db", str(state)]), 0)
            self.assertFalse(state.exists())
            network.assert_not_called()

    def test_submit_resumes_without_duplicate_generation(self):
        plan = self.plan()
        con = dv.db_open(self.root / "state.sqlite", plan)
        try:
            with patch.object(dv, "comfy_json", return_value={"prompt_id": "12345678-1234"}) as call:
                self.assertTrue(dv.submit_one(con, plan["jobs"][0]))
                self.assertEqual(call.call_count, 1)
                self.assertEqual(con.execute("SELECT state FROM runs WHERE shot_id='01'").fetchone()[0],
                                 "queued")
            # Client driver submits only pending records. A second run won't re-submit shot 01.
            dv.atomic_json(self.root / "plan.json", plan)
            with patch.object(dv, "comfy_json", return_value={"prompt_id": "12345678-5678"}) as call:
                self.assertEqual(dv.run_cli(["submit", "--plan", str(self.root / "plan.json"),
                    "--db", str(self.root / "state.sqlite"),
                    "--execute", "--acknowledge-gpu-cost", "--max-jobs", "1"]), 0)
                self.assertEqual(call.call_count, 1)
                self.assertEqual(con.execute("SELECT state FROM runs WHERE shot_id='01'").fetchone()[0],
                                 "queued")
        finally:
            con.close()

    def test_uncertain_submit_never_autoretries(self):
        plan = self.plan()
        con = dv.db_open(self.root / "state.sqlite", plan)
        try:
            with patch.object(dv, "comfy_json", side_effect=TimeoutError("ambiguous")):
                self.assertFalse(dv.submit_one(con, plan["jobs"][0]))
            state = con.execute("SELECT state,error_code FROM runs WHERE shot_id='01'").fetchone()
            self.assertEqual(state, ("uncertain", "submit_unknown"))
        finally:
            con.close()

    def test_known_http_validation_rejection(self):
        plan = self.plan()
        con = dv.db_open(self.root / "state.sqlite", plan)
        try:
            fail = urllib.error.HTTPError("http://127.0.0.1:8188/prompt", 400, "bad", {}, None)
            with patch.object(dv, "comfy_json", side_effect=fail):
                self.assertFalse(dv.submit_one(con, plan["jobs"][0]))
            self.assertEqual(con.execute("SELECT state FROM runs WHERE shot_id='01'").fetchone()[0],
                             "rejected")
        finally:
            con.close()

    def test_collect_output_metadata_and_no_remote_submission(self):
        plan = self.plan()
        con = dv.db_open(self.root / "state.sqlite", plan)
        try:
            dv.set_state(con, "01", "queued", prompt_id="12345678-1234")
            result = {"12345678-1234": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"7": {"videos": [
                    {"filename": "shot_01.mp4", "subfolder": "exports", "type": "output"}]}}}}
            with patch.object(dv, "comfy_json", return_value=result) as api:
                self.assertEqual(dv.collect(con, plan, self.root / "results"), 1)
                self.assertEqual(api.call_args.args[0], "/history/12345678-1234")
            manifest = json.loads((self.root / "results/01/manifest.json").read_text())
            self.assertEqual(manifest["outputs"][0]["filename"], "shot_01.mp4")
            self.assertEqual(con.execute("SELECT state FROM runs WHERE shot_id='01'").fetchone()[0],
                             "done")
        finally:
            con.close()

    def test_path_traversal_and_non_output_assets_rejected(self):
        content = {"outputs": {"5": {"images": [
            {"filename": "../escape.png", "subfolder": "", "type": "output"},
            {"filename": "private.png", "subfolder": "", "type": "input"},
            {"filename": "ok.png", "subfolder": "../secret", "type": "output"},
            {"filename": "valid.png", "subfolder": "shots", "type": "output"}]}}}
        files = dv.outputs_from_history(content)
        self.assertEqual([x["filename"] for x in files], ["valid.png"])

    def _json_file(self, rows):
        path = self.root / "input.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
