"""UE V0.8 signed Worker contract: actual UE inventory, never fake finished media.

Offline only: mocked process, no Unreal Editor invocation or GPU usage.
"""
from __future__ import annotations
import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import agent
import ue_jobs

ASSET_IDS={
    "characters":("CHAR_GPT","CHAR_GEM","CHAR_DS","CHAR_CLA","CHAR_ZERO"),
    "scenes":("SCN_HALL","SCN_ENTRANCE"),
    "shots":tuple("SH%02d"%i for i in range(1,32)),
}


def plan(task="audit_ep01_assets"):
    shots=[{"shot_id":"%02d"%i,"ordinal":i,
            "duration_ms":10000 if i==31 else 5000} for i in range(1,32)]
    return {"task":task,"project_id":"WaitingOffice","episode_id":"EP01",
            "fps":24,"shots":shots,"expected_total_ms":160000}


def report(*, present=False):
    return {group:[{"id":name,"exists":present,"type_valid":present}
                   for name in names] for group,names in ASSET_IDS.items()}


class AssetAuditTests(unittest.TestCase):
    def test_strict_locked_episode_manifest_and_read_only_capabilities(self):
        x=ue_jobs.sanitized_plan(plan())
        self.assertEqual(x["format"],"director_ue_assets_v08")
        self.assertEqual((x["total_frames"],x["total_ms"]),(3840,160000))
        self.assertEqual([k["shot_id"] for k in x["shots"]],
                         ["%02d"%i for i in range(1,32)])
        c=agent.capabilities()
        self.assertIn("audit_ep01_assets",c["jobs"])
        self.assertTrue(c["supports_ep01_native_asset_audit"])
        self.assertFalse(c["supports_rendering"])

    def test_rejects_non_ep01_user_paths_and_changed_timing(self):
        for field,value in [
            ("episode_id","EP02"),("project_id","AnotherProject"),
            ("fps",30),("expected_total_ms",170000),
            ("script","C:/test.py"),("url","https://evil.example"),
        ]:
            bad=plan()
            bad[field]=value
            with self.assertRaises(ue_jobs.JobError):
                ue_jobs.sanitized_plan(bad)
        bad=plan()
        bad["shots"][2]["shot_id"]="04"
        with self.assertRaises(ue_jobs.JobError):
            ue_jobs.sanitized_plan(bad)

    def fake_runner(self, result):
        def run_fixed(_command,_root,logfile,_timeout,_env,_timeout_error,_fail_error):
            (logfile.parent/"result.json").write_text(
                json.dumps(result),encoding="utf-8")
        return run_fixed

    def test_missing_assets_report_is_successful_inventory_not_render(self):
        spec=ue_jobs.sanitized_plan(plan())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/"ue"
            work=Path(directory)/"job"
            with patch.object(ue_jobs,"find_editor_cmd",
                              return_value=Path("C:/UnrealEditor-Cmd.exe")),patch.object(
                              ue_jobs,"run_fixed",
                              side_effect=self.fake_runner({
                                  "ok":True,"shot_count":31,"total_frames":3840,
                                  "asset_audit":report(),
                              })) as runner:
                out=ue_jobs.run_commandlet(spec,root,work)
            self.assertTrue(out["audit_only"])
            self.assertFalse(out["all_assets_present_and_class_valid"])
            self.assertFalse(out["studio_approval_verified"])
            self.assertFalse(out["render_ready"])
            self.assertFalse(out["gpu_render_submitted"])
            self.assertEqual(sum(len(g) for g in out["asset_audit"].values()),38)
            cmd=runner.call_args.args[0]
            self.assertIn("unreal_build_stage.py"," ".join(cmd))
            self.assertEqual(len([x for x in cmd if x.startswith("-script=")]),1)

    def test_existing_assets_must_not_be_misreported_as_approved(self):
        spec=ue_jobs.sanitized_plan(plan())
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(ue_jobs,"find_editor_cmd",
                              return_value=Path("C:/UnrealEditor-Cmd.exe")),patch.object(
                              ue_jobs,"run_fixed",
                              side_effect=self.fake_runner({
                                  "ok":True,"shot_count":31,"total_frames":3840,
                                  "asset_audit":report(present=True),
                              })):
                out=ue_jobs.run_commandlet(spec,Path(directory)/"project",
                                           Path(directory)/"job")
            self.assertTrue(out["all_assets_present_and_class_valid"])
            self.assertFalse(out["studio_approval_verified"])
            self.assertFalse(out["animation_binding_verified"])
            self.assertFalse(out["render_ready"])

    def test_malformed_or_spoofed_results_fail_closed(self):
        spec=ue_jobs.sanitized_plan(plan())
        failures=[
            {"characters":[],"scenes":[],"shots":[]},
            {**report(),"unexpected":True},
            {**report(),"shots":[*report()["shots"][:-1],
                                {"id":"../../outside","exists":True,"type_valid":True}]},
            {**report(),"characters":[{"id":"CHAR_GPT","exists":1,
                                         "type_valid":False},*report()["characters"][1:]]},
        ]
        for bad in failures:
            with self.subTest(bad=str(bad)[:40]):
                with tempfile.TemporaryDirectory() as directory:
                    with patch.object(ue_jobs,"find_editor_cmd",
                                      return_value=Path("C:/UnrealEditor-Cmd.exe")),patch.object(
                                      ue_jobs,"run_fixed",
                                      side_effect=self.fake_runner({
                                          "ok":True,"shot_count":31,"total_frames":3840,
                                          "asset_audit":bad,
                                      })):
                        with self.assertRaisesRegex(
                            ue_jobs.JobError,"ue_asset_audit_invalid"):
                            ue_jobs.run_commandlet(
                                spec,Path(directory)/"project",Path(directory)/"job")

    def test_unreal_audit_function_is_read_only(self):
        source=(ROOT/"unreal_build_stage.py").read_text(encoding="utf-8")
        node=ast.parse(source)
        fn=next(x for x in node.body if isinstance(x,ast.FunctionDef)
                and x.name=="audit_ep01_assets")
        calls=[ast.unparse(x.func) for x in ast.walk(fn)
               if isinstance(x,ast.Call)]
        self.assertIn("unreal.EditorAssetLibrary.does_asset_exist",calls)
        self.assertIn("unreal.EditorAssetLibrary.load_asset",calls)
        forbidden=("spawn_actor","save_","create_asset","delete_asset",
                   "run_mrq","render","subprocess","os.system","exec")
        self.assertFalse([x for x in calls if any(v in x for v in forbidden)])
        self.assertNotIn("traceback",ast.unparse(fn).lower())


if __name__=="__main__":
    unittest.main()
