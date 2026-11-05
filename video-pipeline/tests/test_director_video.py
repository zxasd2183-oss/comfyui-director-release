import copy
import csv
import hashlib
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
            def fake_comfy(endpoint, body=None):
                if endpoint == "/queue":
                    return {"queue_running": [], "queue_pending": []}
                if endpoint.startswith("/object_info/"):
                    name = endpoint.rsplit("/", 1)[-1]
                    return {name: {"input": {}}}
                if endpoint == "/prompt":
                    return {"prompt_id": "12345678-5678"}
                raise AssertionError("Unexpected ComfyUI endpoint")
            with patch.object(dv, "comfy_json", side_effect=fake_comfy) as call:
                self.assertEqual(dv.run_cli(["submit", "--plan", str(self.root / "plan.json"),
                    "--db", str(self.root / "state.sqlite"),
                    "--execute", "--acknowledge-gpu-cost", "--max-jobs", "1"]), 0)
                self.assertEqual(sum(x.args[0] == "/prompt" for x in call.call_args_list), 1)
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


    def test_preflight_read_only_checks_actual_node_schemas_and_queue(self):
        plan = self.plan()
        seen = []
        def local(endpoint, body=None):
            seen.append((endpoint, body))
            if endpoint == "/queue":
                return {"queue_running": [], "queue_pending": []}
            if endpoint.startswith("/object_info/"):
                name = endpoint.rsplit("/", 1)[-1]
                return {name: {"input": {"required": {}}}}
            raise AssertionError("Unexpected endpoint")
        result = dv.preflight_plan(plan, client=local)
        self.assertTrue(result["ok"])
        self.assertFalse(result["generation_submitted"])
        self.assertEqual(result["node_types_checked"], 3)
        self.assertEqual([x[0] for x in seen].count("/queue"), 1)
        self.assertTrue(all(x[1] is None for x in seen))
        self.assertFalse(any(x[0] == "/prompt" for x in seen))

    def test_preflight_rejects_missing_node_without_submitting(self):
        def missing(endpoint, body=None):
            if endpoint.startswith("/object_info/"):
                return {}
            raise AssertionError("Should not check queue after missing node")
        with self.assertRaisesRegex(dv.PlanError, "unavailable"):
            dv.preflight_plan(self.plan(), client=missing)

    def test_preflight_blocks_busy_or_invalid_queue(self):
        def busy(endpoint, body=None):
            if endpoint == "/queue":
                return {"queue_running": [{"prompt_id": "other"}], "queue_pending": []}
            name = endpoint.rsplit("/", 1)[-1]
            return {name: {"input": {}}}
        with self.assertRaisesRegex(dv.PlanError, "not idle"):
            dv.preflight_plan(self.plan(), client=busy)
        def malformed(endpoint, body=None):
            if endpoint == "/queue":
                return {"queue_running": 0, "queue_pending": "unknown"}
            name = endpoint.rsplit("/", 1)[-1]
            return {name: {"input": {}}}
        with self.assertRaisesRegex(dv.PlanError, "invalid shape"):
            dv.preflight_plan(self.plan(), client=malformed)

    def test_preflight_blocks_unsafe_class_and_never_requests_url(self):
        plan = self.plan()
        plan["jobs"][0]["graph"]["6"]["class_type"] = "../internal"
        with self.assertRaisesRegex(dv.PlanError, "Unsafe"):
            dv.preflight_plan(plan, client=lambda *args: self.fail("No HTTP for invalid classes"))

    def test_preflight_cli_does_not_open_database_or_execute(self):
        plan = self.root / "plan-preflight.json"
        dv.atomic_json(plan, self.plan())
        db = self.root / "not-created.sqlite"
        def local(endpoint, body=None):
            if endpoint == "/queue":
                return {"queue_running": [], "queue_pending": []}
            name = endpoint.rsplit("/", 1)[-1]
            return {name: {"input": {}}}
        with patch.object(dv, "comfy_json", side_effect=local) as client:
            self.assertEqual(dv.run_cli(["preflight", "--plan", str(plan)]), 0)
            self.assertFalse(any(x.args[0] == "/prompt" for x in client.call_args_list))
        self.assertFalse(db.exists())

    def test_execute_with_busy_queue_fails_before_prompt_post(self):
        plan = self.root / "plan-busy.json"
        dv.atomic_json(plan, self.plan())
        def local(endpoint, body=None):
            if endpoint == "/queue":
                return {"queue_running": [], "queue_pending": ["existing"]}
            if endpoint == "/prompt":
                self.fail("Preflight must protect against queuing another job")
            name = endpoint.rsplit("/", 1)[-1]
            return {name: {"input": {}}}
        with patch.object(dv, "comfy_json", side_effect=local):
            with self.assertRaisesRegex(dv.PlanError, "not idle"):
                dv.run_cli(["submit", "--plan", str(plan),
                            "--db", str(self.root / "state-busy.sqlite"),
                            "--execute", "--acknowledge-gpu-cost"])


    def _archive_shots(self):
        plan = self.plan()
        directory = self.root / "results"
        directory.mkdir()
        for job in plan["jobs"]:
            folder = directory / job["shot_id"]
            folder.mkdir()
            payload = b"video-" + job["shot_id"].encode()
            name = "000_" + job["shot_id"] + ".mp4"
            (folder / name).write_bytes(payload)
            dv.atomic_json(folder / "manifest.json", {
                "shot_id": job["shot_id"],
                "downloaded": [{
                    "file": name, "sha256": hashlib.sha256(payload).hexdigest(),
                    "bytes": len(payload),
                }]
            })
        return plan, directory

    def test_assemble_verifies_hashes_and_uses_no_shell(self):
        plan, result_dir = self._archive_shots()
        movie = self.root / "movie.mp4"
        calls = []
        def fake_runner(args, **kwargs):
            calls.append(args)
            if args[0] == "ffprobe":
                return type("Result", (), {"returncode": 0,
                    "stdout": json.dumps({"streams": [
                        {"codec_type": "video", "codec_name": "h264",
                         "width": 1280, "height": 720, "pix_fmt": "yuv420p",
                         "avg_frame_rate": "24/1"}]}).encode()})()
            if args[0] == "ffmpeg":
                self.assertEqual(args[:3], ["ffmpeg", "-nostdin", "-hide_banner"])
                self.assertEqual(kwargs.get("check"), False)
                (Path(args[-1])).write_bytes(b"merged MP4 for mock")
                return type("Result", (), {"returncode": 0})()
            self.fail("Unexpected subprocess")
        result = dv.assemble_movie(plan, result_dir, movie, runner=fake_runner)
        self.assertTrue(result["ok"])
        self.assertEqual(result["clips"], 2)
        self.assertEqual(result["gpu_calls"], 0)
        self.assertEqual(movie.read_bytes(), b"merged MP4 for mock")
        self.assertEqual(sum(x[0] == "ffmpeg" for x in calls), 1)
        with self.assertRaisesRegex(dv.PlanError, "new .mp4"):
            dv.assemble_movie(plan, result_dir, movie, runner=fake_runner)

    def test_assemble_rejects_hash_mismatch_without_running_ffmpeg(self):
        plan, result_dir = self._archive_shots()
        (result_dir / "02" / "000_02.mp4").write_bytes(b"tampered")
        with self.assertRaisesRegex(dv.PlanError, "checksum"):
            dv.assemble_movie(plan, result_dir, self.root / "bad.mp4",
                runner=lambda *_args, **_kwargs: self.fail("Should not run ffprobe/ffmpeg"))

    def test_assemble_rejects_missing_clip_or_symlink(self):
        plan, result_dir = self._archive_shots()
        (result_dir / "01" / "000_01.mp4").unlink()
        with self.assertRaisesRegex(dv.PlanError, "path is invalid"):
            dv.archived_clips(plan, result_dir)
        (result_dir / "01" / "000_01.mp4").symlink_to(
            result_dir / "02" / "000_02.mp4")
        with self.assertRaisesRegex(dv.PlanError, "path is invalid"):
            dv.archived_clips(plan, result_dir)

    def test_assemble_rejects_incompatible_streams(self):
        plan, result_dir = self._archive_shots()
        def fake_runner(args, **_kwargs):
            if args[0] == "ffmpeg":
                self.fail("Cannot concatenate incompatible streams")
            width = 1280 if "01/" in args[-1] else 1920
            return type("Result", (), {"returncode": 0,
                "stdout": json.dumps({"streams": [{
                    "codec_type": "video", "codec_name": "h264",
                    "width": width, "height": 720
                }]}).encode()})()
        with self.assertRaisesRegex(dv.PlanError, "streams differ"):
            dv.assemble_movie(plan, result_dir, self.root / "bad.mp4",
                              runner=fake_runner)

    def test_assemble_rejects_corrupt_probe(self):
        plan, result_dir = self._archive_shots()
        def fake_runner(args, **_kwargs):
            return type("Result", (), {"returncode": 0, "stdout": b"not json"})()
        with self.assertRaisesRegex(dv.PlanError, "invalid stream metadata"):
            dv.assemble_movie(plan, result_dir, self.root / "bad.mp4",
                              runner=fake_runner)

    def _json_file(self, rows):
        path = self.root / "input.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
