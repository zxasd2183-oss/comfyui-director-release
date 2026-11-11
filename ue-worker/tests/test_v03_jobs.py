"""Guard V03 job allowlist and Studio-only dispatch."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ue_jobs


def frozen_ep01():
    durations=[3,5,5,6,6,5,5,6,5,6,5,5,4,5,5,5,7,5,5,5,6,5,6,5,4,5,5,6,5,5,5]
    return {
        "task":"build_stage_cameras",
        "project_id":"WaitingOffice", "episode_id":"EP01","fps":24,
        "shots":[{"shot_id":f"{i:02}","ordinal":i,"duration_ms":seconds*1000}
                 for i,seconds in enumerate(durations,1)],
        "expected_total_ms":160000,
    }


class StageJobTest(unittest.TestCase):
    def test_stage_accepts_only_locked_ep01(self):
        item=ue_jobs.sanitized_plan(frozen_ep01())
        self.assertEqual(item["format"],"director_ue_stage_v03")
        self.assertEqual(len(item["shots"]),31)
        self.assertEqual(item["total_frames"],3840)
        self.assertEqual(item["shots"][-1]["end_frame"],3840)

    def test_stage_rejects_other_episode_and_inline_python(self):
        for k,v in [("episode_id","EP02"),("fps",30),("project_id","Other")]:
            bad=frozen_ep01()
            bad[k]=v
            with self.assertRaises(ue_jobs.JobError):
                ue_jobs.sanitized_plan(bad)
        bad=frozen_ep01()
        bad["script"]="evil.py"
        with self.assertRaises(ue_jobs.JobError):
            ue_jobs.sanitized_plan(bad)

    def test_v02_original_job_still_accepted(self):
        job=frozen_ep01()
        job["task"]="build_episode_timeline"
        self.assertEqual(ue_jobs.sanitized_plan(job)["format"],"director_ue_timeline_v1")

    def test_invalid_stage_plan_has_no_workspace_side_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            manager=ue_jobs.JobManager(lambda:root,runner=lambda *x: None)
            bad=frozen_ep01()
            bad["shots"][0]["shot_id"]="../"
            with self.assertRaises(ue_jobs.JobError):
                manager.submit(bad)
            self.assertFalse((root/"Jobs").exists())


if __name__=="__main__":
    unittest.main()
