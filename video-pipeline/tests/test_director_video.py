import copy
import csv
import hashlib
import json
import shutil
import subprocess
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

    def studio_handoff(self):
        approved={"status":"approved","fields":{
            "fps":"24","width":"1080","height":"1920"},
            "revision":1,"approved_revision":1}
        package={"schema":"director_studio_video_handoff_v1",
            "gpu_dispatch_authorized":False,"renderer_connected":False,
            "project_id":"WaitingOffice","episode_id":"EP01","shot_id":"01",
            "duration_ms":5000,"ordinal":1,"blockers":[
                "video_render_executor_not_connected"],
            "video_plan":{"unit_id":"01","revision":2,"status":"in_review",
                "fields":{"prompt":"人物缓慢抬头","duration":"5","fps":"24",
                          "width":"1080","height":"1920","seed":"123"}},
            "upstream":{"settings":approved,
                "shot_plans":{"status":"approved","fields":{"scene_id":"HALL"}},
                "storyboards":{"status":"approved","fields":{"composition":"正面"}},
                "white_models":{"status":"approved","fields":{"quality":"粗白模"}}},
            "scene":{"scene_id":"HALL","status":"approved"},"props":[]}
        checksum=hashlib.sha256(json.dumps(package,sort_keys=True,
            ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
        return {"ok":True,"package":package,"package_sha256":checksum,
            "checksum_type":"sha256_canonical_json_not_signature","gpu_action":False}

    def test_studio_handoff_only_prepares_offline_when_all_inputs_approved(self):
        handoff=self.studio_handoff()
        with patch.object(dv,"comfy_json") as network:
            plan=dv.build_studio_handoff_plan(handoff,self.workflow,self.binding)
            self.assertEqual(plan["shot_count"],1)
            self.assertEqual(plan["jobs"][0]["frames"],120)
            self.assertEqual(plan["jobs"][0]["graph"]["6"]["inputs"]["text"],
                             "人物缓慢抬头")
            self.assertEqual(plan["studio_handoff"]["package_sha256"],
                             handoff["package_sha256"])
            self.assertFalse(plan["studio_handoff"]["checksum_is_signature"])
            self.assertFalse(plan["gpu_actions_performed"])
            network.assert_not_called()
        # The public-facing CLI is still offline and only creates an inert plan.
        package_file=self.root/"handoff.json"
        workflow_file=self.root/"api.json"
        bindings_file=self.root/"bindings.json"
        output=self.root/"studio_plan.json"
        for path,value in ((package_file,handoff),(workflow_file,self.workflow),
                           (bindings_file,self.binding)):
            dv.atomic_json(path,value)
        with patch.object(dv,"comfy_json") as network:
            self.assertEqual(dv.run_cli(["prepare-studio","--package",str(package_file),
                "--workflow",str(workflow_file),"--bindings",str(bindings_file),
                "--out",str(output)]),0)
            network.assert_not_called()
        self.assertEqual(dv.load_plan(output)["shot_count"],1)

    def test_studio_full_episode_import_and_no_partial_queue(self):
        single=self.studio_handoff()
        bundle={"schema":"director_studio_episode_handoff_v1",
            "project_id":"WaitingOffice","episode_id":"EP01",
            "shot_count":1,"total_duration_ms":5000,"shot_ids":["01"],
            "packages":[single],"blocked":[],"all_ready":True,
            "gpu_dispatch_authorized":False}
        def doc(data):
            return {"ok":True,"bundle":data,
                "bundle_sha256":hashlib.sha256(json.dumps(
                    data,sort_keys=True,ensure_ascii=False,
                    separators=(",",":")).encode()).hexdigest(),
                "checksum_type":"sha256_canonical_json_not_signature",
                "gpu_action":False}
        ready=doc(bundle)
        with patch.object(dv,"comfy_json") as network:
            plan=dv.build_studio_episode_plan(
                ready,self.workflow,self.binding)
            network.assert_not_called()
        self.assertEqual(plan["shot_count"],1)
        self.assertEqual(plan["total_seconds"],5)
        self.assertEqual(plan["jobs"][0]["frames"],120)
        self.assertEqual(plan["studio_episode_handoff"]["bundle_sha256"],
                         ready["bundle_sha256"])
        self.assertFalse(plan["gpu_actions_performed"])
        file=self.root/"episode.json"
        graph=self.root/"workflow.json"
        mapping=self.root/"bindings.json"
        output=self.root/"episode-plan.json"
        for path,value in ((file,ready),(graph,self.workflow),
                           (mapping,self.binding)):
            dv.atomic_json(path,value)
        with patch.object(dv,"comfy_json") as network:
            self.assertEqual(dv.run_cli(["prepare-studio-batch",
                "--package",str(file),"--workflow",str(graph),
                "--bindings",str(mapping),"--out",str(output)]),0)
            network.assert_not_called()
        self.assertEqual(dv.load_plan(output)["shot_count"],1)
        incomplete=copy.deepcopy(bundle)
        incomplete["shot_count"]=2
        incomplete["shot_ids"].append("02")
        incomplete["total_duration_ms"]=8000
        incomplete["blocked"]=[{"shot_id":"02","reasons":["video_plan_not_found"]}]
        incomplete["all_ready"]=False
        with self.assertRaisesRegex(dv.PlanError,"blocked shots"):
            dv.build_studio_episode_plan(doc(incomplete),self.workflow,self.binding)
        wrong=copy.deepcopy(ready)
        wrong["bundle"]["shot_ids"]=["02"]
        with self.assertRaisesRegex(dv.PlanError,"checksum mismatch"):
            dv.build_studio_episode_plan(wrong,self.workflow,self.binding)

    def test_studio_handoff_blocks_tampering_and_missing_approvals(self):
        package=self.studio_handoff()
        altered=copy.deepcopy(package)
        altered["package"]["video_plan"]["fields"]["prompt"]="被替换的提示词"
        with self.assertRaisesRegex(dv.PlanError,"checksum mismatch"):
            dv.build_studio_handoff_plan(altered,self.workflow,self.binding)
        for change,reason in [
            (lambda d:d["package"].update(blockers=[
                "storyboards_not_approved","video_render_executor_not_connected"]),
             "upstream approvals incomplete"),
            (lambda d:d["package"]["upstream"]["settings"].update(status="draft"),
             "upstream approval missing"),
            (lambda d:d["package"]["video_plan"]["fields"].update(fps="30"),
             "output specification"),
            (lambda d:d["package"].update(gpu_dispatch_authorized=True),
             "cannot grant GPU authorization")
        ]:
            data=copy.deepcopy(package)
            change(data)
            data["package_sha256"]=hashlib.sha256(json.dumps(
                data["package"],sort_keys=True,ensure_ascii=False,
                separators=(",",":")).encode()).hexdigest()
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(dv.PlanError,reason):
                    dv.build_studio_handoff_plan(data,self.workflow,self.binding)
        with self.assertRaisesRegex(dv.PlanError,"exactly when"):
            dv.build_studio_handoff_plan(package,self.workflow,
                {**self.binding,"image":{"node":"6","input":"text"}})
        with self.assertRaisesRegex(dv.PlanError,"safe ComfyUI input basename"):
            dv.build_studio_handoff_plan(package,self.workflow,
                {**self.binding,"image":{"node":"6","input":"text"}},
                "../private.png")

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



    def test_preflight_detects_h3_frame_limit_before_spending_gpu(self):
        # A model may support fewer frames than seconds * fps requests.
        plan = self.plan()
        def local(endpoint, body=None):
            if endpoint == "/queue":
                self.fail("Invalid frame size must abort before queue execution")
            name = endpoint.rsplit("/", 1)[-1]
            fields = {}
            if name == "FrameNode":
                fields = {"required": {
                    "frames": ["INT", {"min": 1, "max": 100}],
                    "seed": ["INT", {"min": 0}],
                }}
            return {name: {"input": fields}}
        with self.assertRaisesRegex(dv.PlanError, "outside installed node bounds"):
            dv.preflight_plan(plan, client=local)

    def test_preflight_checks_invalid_choices_and_wrong_types(self):
        plan = self.plan()
        plan["jobs"][0]["graph"]["6"]["inputs"]["text"] = 42
        def local(endpoint, body=None):
            if endpoint == "/queue":
                self.fail("Wrong input type should abort")
            name = endpoint.rsplit("/", 1)[-1]
            schema = {"required": {}}
            if name == "TextNode":
                schema = {"required": {"text": [["allowed", "different"]]}}
            return {name: {"input": schema}}
        with self.assertRaisesRegex(dv.PlanError, "choice unavailable"):
            dv.preflight_plan(plan, client=local)


    def test_inspect_workflow_redacts_prompt_values_and_reports_bindings(self):
        graph = copy.deepcopy(self.workflow)
        graph["6"]["inputs"]["text"] = "PRIVATE PROMPT SECRET"
        graph["9"]["inputs"]["seed"] = 123456789
        value = dv.inspect_workflow(graph)
        self.assertTrue(value["values_redacted"])
        self.assertEqual(value["network_calls"], 0)
        self.assertEqual(value["node_count"], 3)
        self.assertEqual(value["node_inventory"][0]["id"], "6")
        self.assertEqual(value["node_inventory"][-1]["inputs"][0]["kind"], "link")
        self.assertNotIn("PRIVATE PROMPT SECRET", json.dumps(value))
        self.assertNotIn("123456789", json.dumps(value))

    def test_inspect_cli_makes_no_network_calls(self):
        graph = self.root / "api.json"
        dv.atomic_json(graph, self.workflow)
        with patch.object(dv, "comfy_json") as network:
            self.assertEqual(dv.run_cli(["inspect", "--workflow", str(graph)]), 0)
            network.assert_not_called()

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

    def test_export_complete_studio_delivery_folder_offline(self):
        plan, archive=self._archive_shots()
        receipts=[]
        for number,sid in enumerate(("01","02"),start=1):
            receipt={"project_id":"WaitingOffice","episode_id":"EP01",
                "shot_id":sid,"video_revision":number,
                "package_sha256":hashlib.sha256(sid.encode()).hexdigest()}
            receipts.append(receipt)
            manifest=archive/sid/"manifest.json"
            data=json.loads(manifest.read_text())
            data["prompt_id"]="real_prompt_"+sid
            dv.atomic_json(manifest,data)
        plan["studio_episode_handoff"]={
            "project_id":"WaitingOffice","episode_id":"EP01",
            "bundle_sha256":"a"*64,"shot_receipts":receipts,
            "manual_gpu_execution_required":True}
        out=self.root/"studio-delivery"
        with patch.object(dv,"comfy_json") as network:
            result=dv.export_studio_delivery(plan,archive,out)
            network.assert_not_called()
        self.assertEqual(result["shot_count"],2)
        self.assertEqual(result["gpu_actions"],0)
        manifest=dv.read_json(out/"manifest.json")
        self.assertEqual(manifest["manifest"]["schema"],
                         "director_studio_video_delivery_v1")
        self.assertEqual(manifest["manifest"]["shot_count"],2)
        self.assertEqual(manifest["manifest"]["episode_bundle_sha256"],"a"*64)
        self.assertEqual([i["shot_id"] for i in manifest["manifest"]["shots"]],
                         ["01","02"])
        for item in manifest["manifest"]["shots"]:
            self.assertEqual(dv.file_checksum(out/item["filename"]),
                             (item["file_sha256"],item["size_bytes"]))
            self.assertEqual(item["prompt_id"],"real_prompt_"+item["shot_id"])
        with self.assertRaisesRegex(dv.PlanError,"new absolute directory"):
            dv.export_studio_delivery(plan,archive,out)
        (archive/"02"/"000_02.mp4").write_bytes(b"tampered archive")
        with self.assertRaisesRegex(dv.PlanError,"checksum"):
            dv.export_studio_delivery(plan,archive,self.root/"rejected-delivery")
        self.assertFalse((self.root/"rejected-delivery").exists())

    def test_export_studio_delivery_requires_matching_receipts_and_prompt(self):
        plan,archive=self._archive_shots()
        with self.assertRaisesRegex(dv.PlanError,"requires versioned"):
            dv.export_studio_delivery(plan,archive,self.root/"invalid")
        receipt={"project_id":"WaitingOffice","episode_id":"EP01",
            "shot_id":"01","video_revision":1,"package_sha256":"f"*64}
        plan["studio_episode_handoff"]={
            "project_id":"WaitingOffice","episode_id":"EP01",
            "bundle_sha256":"a"*64,"shot_receipts":[receipt,dict(receipt)]}
        with self.assertRaisesRegex(dv.PlanError,"shot/receipt mismatch"):
            dv.export_studio_delivery(plan,archive,self.root/"invalid")
        plan["studio_episode_handoff"]["shot_receipts"][1]={
            **receipt,"shot_id":"02"}
        with self.assertRaisesRegex(dv.PlanError,"Invalid collected ComfyUI prompt ID"):
            dv.export_studio_delivery(plan,archive,self.root/"invalid")

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


    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "ffmpeg/ffprobe not installed")
    def test_real_ffmpeg_stitches_two_short_safe_clips(self):
        plan = self.plan()
        result_dir = self.root / "real-clips"
        result_dir.mkdir()
        for job in plan["jobs"]:
            directory = result_dir / job["shot_id"]
            directory.mkdir()
            name = "000_clip.mp4"
            dest = directory / name
            cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                   "-f", "lavfi", "-i", "color=c=black:s=64x64:r=12:d=0.5",
                   "-an", "-c:v", "mpeg4", "-q:v", "2", "-y", str(dest)]
            proc = subprocess.run(cmd, capture_output=True, check=False, timeout=25)
            self.assertEqual(proc.returncode, 0, proc.stderr[:300])
            checksum, size = dv.file_checksum(dest)
            dv.atomic_json(directory / "manifest.json", {
                "shot_id": job["shot_id"],
                "downloaded": [{"file": name, "sha256": checksum, "bytes": size}]
            })
        final = self.root / "real-concat.mp4"
        output = dv.assemble_movie(plan, result_dir, final)
        self.assertTrue(output["ok"])
        self.assertGreater(final.stat().st_size, 0)
        signature = dv.video_stream_signature(final)
        self.assertEqual(signature[0][0], "video")

    def _json_file(self, rows):
        path = self.root / "input.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
