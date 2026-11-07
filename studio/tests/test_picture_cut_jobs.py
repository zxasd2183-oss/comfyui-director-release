"""Persistent owner-confirmed CPU picture assembly queue; no GPU actions."""
from contextlib import closing
import http.client
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parent))
import production_core as core
import video_results as media
import picture_cuts as cuts
import picture_cut_jobs as jobs
import studio_server as server
import test_video_handoff_integration as fixture
import test_video_results as sample
import test_picture_cuts as picture_fixture
from studio_identity import COOKIE_SID


class PictureQueueTests(unittest.TestCase):
    upload=fixture.StudioToGpuHandoffTests.upload
    save=fixture.StudioToGpuHandoffTests.save
    review=fixture.StudioToGpuHandoffTests.review
    build_approved_chain=fixture.StudioToGpuHandoffTests.build_approved_chain
    begin=sample.VideoReturnTests.begin
    chunks=sample.VideoReturnTests.chunks
    finish=sample.VideoReturnTests.finish
    review_take_result=sample.VideoReturnTests.review_take_result
    review_video_plan_rejected_then_revised=(
        sample.VideoReturnTests.review_video_plan_rejected_then_revised)

    def setUp(self):
        sample.VideoReturnTests.setUp(self)
        with closing(core.open_db(self.db)) as db:
            media.prepare_schema(db)
            cuts.prepare_schema(db)
            jobs.prepare_schema(db)

    def ready(self):
        start=self.begin()
        self.chunks(start["upload_id"])
        take=self.finish(start["upload_id"])
        self.review_take_result(take["take_id"])
        return cuts.get_readiness(self.db,"WaitingOffice","EP01")

    def task(self,ready,acknowledge=True):
        return {"project_id":"WaitingOffice","episode_id":"EP01",
            "source_manifest_sha256":ready["source_manifest_sha256"],
            "acknowledge_local_cpu":acknowledge}

    def test_enqueue_requires_approved_shot_exact_hash_and_cpu_confirmation(self):
        blocked=cuts.get_readiness(self.db,"WaitingOffice","EP01")
        with self.assertRaises(jobs.PictureJobError) as ctx:
            jobs.enqueue(self.db,self.task(blocked),"test_owner")
        self.assertEqual(ctx.exception.reason,"picture_cut_source_changed_or_incomplete")
        ready=self.ready()
        with self.assertRaises(jobs.PictureJobError) as ctx:
            jobs.enqueue(self.db,self.task(ready,False),"test_owner")
        self.assertEqual(ctx.exception.reason,"local_cpu_cost_acknowledgment_required")
        changed=self.task(ready)
        changed["source_manifest_sha256"]="0"*64
        with self.assertRaises(jobs.PictureJobError) as ctx:
            jobs.enqueue(self.db,changed,"test_owner")
        self.assertEqual(ctx.exception.reason,"picture_cut_source_changed_or_incomplete")
        result=jobs.enqueue(self.db,self.task(ready),"test_owner")
        self.assertEqual(result["status"],"queued")
        self.assertFalse(result["gpu_action"])
        dup=jobs.enqueue(self.db,self.task(ready),"test_owner")
        self.assertTrue(dup["existing"])
        self.assertEqual(dup["job_id"],result["job_id"])
        self.assertEqual(len(jobs.list_jobs(
            self.db,"WaitingOffice","EP01")["jobs"]),1)

    def test_worker_emits_validated_picture_cut_with_no_gpu_dispatch(self):
        ready=self.ready()
        task=jobs.enqueue(self.db,self.task(ready),"test_owner")
        with patch("picture_cut_jobs.assemble",wraps=cuts.assemble) as make:
            done=jobs.process_one(self.db,runner=picture_fixture.PictureCutTests.mock_runner)
            self.assertTrue(done["ok"])
            self.assertEqual(make.call_count,1)
        self.assertEqual(done["status"],"done")
        self.assertFalse(done["gpu_action"])
        self.assertTrue(done["cut_id"].startswith("CUT_"))
        current=jobs.list_jobs(self.db,"WaitingOffice","EP01")["jobs"][0]
        self.assertEqual(current["job_id"],task["job_id"])
        self.assertEqual(current["status"],"done")
        self.assertEqual(current["attempts"],1)
        self.assertEqual(jobs.enqueue(
            self.db,self.task(ready),"test_owner")["status"],"done")
        self.assertIsNone(jobs.process_one(self.db))
        with closing(core.open_db(self.db,initialize=False)) as db:
            self.assertTrue(core.verify_chain(db))

    def test_worker_failed_if_source_changes_after_queue(self):
        ready=self.ready()
        jobs.enqueue(self.db,self.task(ready),"test_owner")
        self.review_video_plan_rejected_then_revised()
        with patch("picture_cut_jobs.assemble") as renderer:
            done=jobs.process_one(self.db)
            renderer.assert_not_called()
        self.assertEqual(done["status"],"failed")
        self.assertEqual(done["error_code"],"picture_cut_source_changed_or_incomplete")
        self.assertFalse(cuts.list_cuts(
            self.db,"WaitingOffice","EP01")["picture_cuts"])

    def test_restart_reclaims_once_without_infinite_retries(self):
        ready=self.ready()
        enqueued=jobs.enqueue(self.db,self.task(ready),"test_owner")
        with closing(core.open_db(self.db)) as db:
            db.execute("UPDATE studio_picture_cut_jobs SET "
                "status='running',attempts=1 WHERE job_id=?",
                (enqueued["job_id"],))
        self.assertEqual(jobs.recover_running(self.db),1)
        self.assertEqual(jobs.list_jobs(
            self.db,"WaitingOffice","EP01")["jobs"][0]["status"],"queued")
        done=jobs.process_one(self.db,
            runner=picture_fixture.PictureCutTests.mock_runner)
        self.assertEqual(done["status"],"done")
        self.assertEqual(jobs.list_jobs(
            self.db,"WaitingOffice","EP01")["jobs"][0]["attempts"],2)
        with closing(core.open_db(self.db)) as db:
            db.execute("UPDATE studio_picture_cut_jobs SET "
                "status='running',attempts=2 WHERE job_id=?",
                (enqueued["job_id"],))
        self.assertEqual(jobs.recover_running(self.db),1)
        self.assertEqual(jobs.list_jobs(
            self.db,"WaitingOffice","EP01")["jobs"][0]["status"],"failed")

    def test_http_job_api_requires_owner_csrf_and_explicit_cpu(self):
        ready=self.ready()
        app=server.StudioServer(str(Path(self.db).with_name("queue-console.sqlite")),
            poller=server.Poller(probe=lambda _:{"ok":False}),
            bind=("127.0.0.1",0))
        app.production_db_path=self.db
        app.identity=sample.MockOwner()
        import threading
        task=threading.Thread(target=app.serve_forever,daemon=True)
        task.start()
        common={"Host":"127.0.0.1:8900",
            "X-Forwarded-Proto":"https",
            "X-Forwarded-Host":"jipite.borealos.cn",
            "X-Director-Studio-Auth-Mode":"microsoft",
            "Cookie":COOKIE_SID+"="+sample.SID,
            "Origin":"https://jipite.borealos.cn",
            "Content-Type":"application/json"}
        try:
            def request(method,path,payload=None,overrides=None):
                connection=http.client.HTTPConnection("127.0.0.1",
                    app.server_port,timeout=8)
                connection.request(method,path,
                    body=json.dumps(payload).encode() if payload is not None else None,
                    headers={**common,**(overrides or {})})
                reply=connection.getresponse()
                status,body=reply.status,json.loads(reply.read())
                connection.close()
                return status,body
            query="?project=WaitingOffice&episode=EP01"
            self.assertEqual(request("GET","/api/v1/picture-cuts/jobs"+query,
                                     overrides={"Cookie":""})[0],401)
            payload={"csrf":sample.CSRF,**self.task(ready)}
            self.assertEqual(request("POST","/api/v1/picture-cuts/assemble",
                                     payload,{"Cookie":""})[0],401)
            self.assertEqual(request("POST","/api/v1/picture-cuts/assemble",
                                     {**payload,"csrf":"wrong"})[0],403)
            status,created=request("POST","/api/v1/picture-cuts/assemble",payload)
            self.assertEqual(status,202,created)
            self.assertEqual(created["status"],"queued")
            self.assertEqual(request("GET","/api/v1/picture-cuts/jobs"+query)[0],200)
        finally:
            app.shutdown();app.server_close();task.join(timeout=4)


if __name__=="__main__":
    unittest.main()
