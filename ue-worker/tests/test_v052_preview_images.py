"""Read-only authenticated PNG proof tests; never start Unreal/GPU."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import ue_jobs
from test_v04_archive import valid_test_png


class PreviewImageAPITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_id = "d" * 32
        self.raw = valid_test_png()
        self.sha = hashlib.sha256(self.raw).hexdigest()
        self.folder = self.root / "Outputs" / "V04" / self.job_id / "Previews"
        self.folder.mkdir(parents=True)
        shots = []
        for shot_id in ("01", "13", "26", "31"):
            name = f"WaitingOffice_EP01_SH{shot_id}_V03_V04_0000.png"
            (self.folder / name).write_bytes(self.raw)
            shots.append({
                "shot_id": shot_id, "filename": name,
                "relative_path": f"Outputs/V04/{self.job_id}/Previews/{name}",
                "bytes": len(self.raw), "sha256": self.sha,
                "width": 720, "height": 1280,
            })
        self.manager = ue_jobs.JobManager(lambda: self.root)
        self.manager.jobs[self.job_id] = {
            "ok": True, "job_id": self.job_id,
            "state": "succeeded", "task": "render_previs_stills",
            "project_id": "WaitingOffice", "episode_id": "EP01",
            "result": {"preview_count": 4, "screenshots": shots},
        }
        self.original_manager = agent.JOB_MANAGER
        agent.JOB_MANAGER = self.manager
        self.server = agent.ThreadingHTTPServer(("127.0.0.1", 0), agent.Handler)
        self.server.token = "e" * 64
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        agent.JOB_MANAGER = self.original_manager
        self.tmp.cleanup()

    def request(self, suffix, *, authorized=True):
        headers = {"Authorization": "Bearer " + "e"*64} if authorized else {}
        req = urllib.request.Request(self.url + suffix, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as err:
            return err.code, dict(err.headers), err.read()

    def route(self, shot="01", job=None):
        return f"/v5/jobs/{job or self.job_id}/previews/{shot}"

    def test_four_shots_return_exact_original_png_bytes(self):
        for shot in ("01", "13", "26", "31"):
            code, headers, data = self.request(self.route(shot))
            self.assertEqual(code, 200)
            self.assertEqual(headers["Content-Type"], "image/png")
            self.assertEqual(headers["X-Director-PNG-SHA256"], self.sha)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(int(headers["Content-Length"]), len(self.raw))
            self.assertEqual(data, self.raw)

    def test_deny_unauthorized_unsafe_paths_and_unapproved_shots(self):
        self.assertEqual(self.request(self.route(), authorized=False)[0], 401)
        for route in (
            self.route("02"), self.route("../../worker.token"),
            "/v5/jobs/" + "z"*32 + "/previews/01",
            self.route("01?path=secret"),
        ):
            self.assertEqual(self.request(route)[0], 404)

    def test_disallow_nonterminal_jobs_and_receipt_tampering(self):
        entry = self.manager.jobs[self.job_id]
        entry["state"] = "running"
        code, _, data = self.request(self.route())
        self.assertEqual(code, 404)
        self.assertEqual(json.loads(data)["reason"], "preview_job_not_completed")
        entry["state"] = "succeeded"
        entry["result"]["screenshots"][0]["relative_path"] = "../worker.token"
        self.assertEqual(json.loads(self.request(self.route())[2])["reason"],
                         "preview_receipt_invalid")

    def test_refuse_changed_image_bytes_and_symlinks(self):
        file = self.folder / "WaitingOffice_EP01_SH01_V03_V04_0000.png"
        data = bytearray(self.raw)
        data[128] ^= 1
        file.write_bytes(data)
        self.assertEqual(json.loads(self.request(self.route())[2])["reason"],
                         "preview_image_hash_mismatch")
        file.unlink()
        fake = self.root / "secret.png"
        fake.write_bytes(self.raw)
        try:
            file.symlink_to(fake)
        except (OSError, NotImplementedError):
            return
        self.assertEqual(json.loads(self.request(self.route())[2])["reason"],
                         "preview_image_unavailable")


if __name__ == "__main__":
    unittest.main()
