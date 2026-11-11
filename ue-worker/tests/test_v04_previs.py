"""Offline contracts: V04 fixed camera proof frames, output integrity and plugin isolation."""
from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ue_jobs
import ue_previs

DURATIONS=[3,5,5,6,6,5,5,6,5,6,5,5,4,5,5,5,7,5,5,5,6,5,6,5,4,5,5,6,5,5,5]


def frozen_previs():
    return {
        "task":"render_previs_stills",
        "project_id":"WaitingOffice","episode_id":"EP01","fps":24,
        "shots":[{"shot_id":f"{i:02}","ordinal":i,"duration_ms":seconds*1000}
                 for i,seconds in enumerate(DURATIONS,1)],
        "expected_total_ms":160000,
    }


class PrevisContracts(unittest.TestCase):
    def test_fixed_shots_and_frozen_episode(self):
        data=ue_jobs.sanitized_plan(frozen_previs())
        self.assertEqual(data["format"],"director_ue_previs_v04")
        self.assertEqual(data["total_frames"],3840)
        self.assertEqual(ue_previs.FRAME_SHOTS,("01","13","26","31"))
        for key,value in [("project_id","Unauthorized"),("episode_id","EP02"),("fps",30)]:
            bad=frozen_previs()
            bad[key]=value
            with self.assertRaises(ue_jobs.JobError):
                ue_jobs.sanitized_plan(bad)
        bad=frozen_previs()
        bad["shots"][10]["shot_id"]="UNTRUSTED"
        with self.assertRaises(ue_jobs.JobError):
            ue_jobs.sanitized_plan(bad)
        bad=frozen_previs()
        bad["command"]="cmd.exe"
        with self.assertRaises(ue_jobs.JobError):
            ue_jobs.sanitized_plan(bad)

    def test_png_header_and_dimensions(self):
        with tempfile.TemporaryDirectory() as td:
            png=Path(td)/"preview.png"
            png.write_bytes(
                ue_previs.PNG_MAGIC + b"\x00\x00\x00\x0dIHDR" +
                struct.pack(">II",720,1280) +
                bytes(2100)
            )
            self.assertEqual(ue_previs.read_png_dimensions(png),(720,1280))
            png.write_bytes(b"notpng")
            with self.assertRaises(ValueError):
                ue_previs.read_png_dimensions(png)

    def test_plugin_enablement_has_exact_manifest_and_backup(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            project=ue_jobs.ensure_project(root)
            original=project.read_bytes()
            work=root/"Jobs"/("a"*32)
            ue_previs.ensure_mrq_plugin(project,work)
            loaded=json.loads(project.read_text())
            self.assertEqual(loaded["Plugins"][-1],
                             {"Name":"MovieRenderPipeline","Enabled":True})
            self.assertEqual((work/"uproject_before_mrq.json").read_bytes(),original)
            self.assertEqual(project,ue_jobs.ensure_project(root))
            # The second job's run does not rewrite the plugin or its backup.
            extra=root/"Jobs"/("b"*32)
            ue_previs.ensure_mrq_plugin(project,extra)
            self.assertFalse(extra.exists())

    def test_plugin_migration_refuses_unknown_project(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            project=ue_jobs.ensure_project(root)
            modified=json.loads(project.read_text())
            modified["Description"]="User modified project; leave alone"
            project.write_text(json.dumps(modified))
            original=project.read_text()
            with self.assertRaises(ue_jobs.JobError):
                ue_previs.ensure_mrq_plugin(project,root/"Jobs"/("c"*32))
            self.assertEqual(project.read_text(),original)

    def test_previews_can_be_repeated_after_restart_without_daily_quota(self):
        from unittest.mock import patch
        import time
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            folder=root/"JobStatus"
            folder.mkdir()
            (folder/"preview_budget_v04.json").write_text("{broken")
            with patch.object(ue_previs,"run_previs",return_value={
                "preview_count":4,"format":"png",
            }):
                for _ in range(5):
                    manager=ue_jobs.JobManager(lambda:root)
                    submission=manager.submit(frozen_previs())
                    for _ in range(200):
                        item=manager.lookup(submission["job_id"])
                        if item["state"] == "succeeded":
                            break
                        time.sleep(.01)
                    self.assertEqual(item["state"],"succeeded")

    def test_missing_real_v03_map_causes_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.assertRaises(ue_jobs.JobError):
                ue_previs.validate_existing_stage(root)
            self.assertFalse((root/"Outputs").exists())


if __name__ == "__main__":
    unittest.main()
