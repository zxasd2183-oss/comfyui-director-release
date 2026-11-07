"""Offline all-approved picture cut + owner review; never GPU or public media."""
from contextlib import closing
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parent))
import production_core as core
import picture_cuts as cuts
import video_results as media
import studio_server as web
import test_video_results as sample
import test_video_handoff_integration as fixture
from studio_identity import COOKIE_SID


class PictureCutTests(unittest.TestCase):
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
            cuts.prepare_schema(db)

    @staticmethod
    def mock_runner(args,**kwargs):
        if args[0]=="/usr/bin/ffprobe":
            return type("Result",(),{"returncode":0,
                "stdout":json.dumps({"streams":[{
                    "codec_type":"video","codec_name":"h264",
                    "width":1080,"height":1920,"pix_fmt":"yuv420p",
                    "avg_frame_rate":"24/1"}],
                    "format":{"duration":"3.0"}}).encode()})()
        if args[0]=="/usr/bin/ffmpeg":
            Path(args[-1]).write_bytes(b"picture cut"+b"F"*512)
            return type("Result",(),{"returncode":0,"stdout":b""})()
        raise AssertionError("Unexpected subprocess: "+str(args[:2]))

    def approved_shot(self):
        start=self.begin()
        self.chunks(start["upload_id"])
        take=self.finish(start["upload_id"])
        self.review_take_result(take["take_id"])
        return take["take_id"]

    def test_all_approved_source_ready_then_assemble_and_review(self):
        before=cuts.get_readiness(self.db,"WaitingOffice","EP01")
        self.assertFalse(before["ready"])
        self.assertIn("current_approved_video_take_missing",
                      before["blocked"][0]["reasons"])
        take=self.approved_shot()
        ready=cuts.get_readiness(self.db,"WaitingOffice","EP01")
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["approved_count"],1)
        self.assertEqual(ready["shot_count"],1)
        self.assertEqual(ready["source_manifest"]["shots"][0]["take_id"],take)
        invoked=[]
        def safe_run(args,**kwargs):
            invoked.append(args[0])
            return self.mock_runner(args,**kwargs)
        done=cuts.assemble(self.db,"WaitingOffice","EP01","local_test",
                           runner=safe_run)
        self.assertEqual(done["status"],"in_review")
        self.assertFalse(done["gpu_action"])
        self.assertFalse(done["sound_mastered"])
        self.assertIn("/usr/bin/ffmpeg",invoked)
        first_id=done["cut_id"]
        second=cuts.assemble(self.db,"WaitingOffice","EP01","local_test",
                             runner=safe_run)
        self.assertTrue(second["already_assembled"])
        self.assertEqual(second["cut_id"],first_id)
        listed=cuts.list_cuts(self.db,"WaitingOffice","EP01")["picture_cuts"]
        self.assertEqual(len(listed),1)
        self.assertTrue(listed[0]["source_current"])
        path,size=cuts.get_cut_file(self.db,"WaitingOffice","EP01",first_id)
        self.assertEqual(size,len(path.read_bytes()))
        self.assertGreaterEqual(size,128)
        reviewed=cuts.review_cut(self.db,{
            "project_id":"WaitingOffice","episode_id":"EP01",
            "cut_id":first_id,"decision":"approve",
            "rationale":"已完整复核镜头顺序、时长、运动连续性，但音频尚未混制。"},
            "owner_picture_test")
        self.assertEqual(reviewed["status"],"approved")
        self.assertFalse(reviewed["final_audio_mixed"])
        with self.assertRaises(cuts.PictureCutError) as ctx:
            cuts.review_cut(self.db,{
                "project_id":"WaitingOffice","episode_id":"EP01",
                "cut_id":first_id,"decision":"approve",
                "rationale":"再次批准此前的画面初剪。"},
                "owner_picture_test")
        self.assertEqual(ctx.exception.reason,"picture_cut_already_reviewed")
        with closing(core.open_db(self.db,initialize=False)) as db:
            self.assertTrue(core.verify_chain(db))

    def test_stale_version_prevents_cut_review_and_new_assembly(self):
        self.approved_shot()
        done=cuts.assemble(self.db,"WaitingOffice","EP01","local_test",
                           runner=self.mock_runner)
        self.review_video_plan_rejected_then_revised()
        after=cuts.get_readiness(self.db,"WaitingOffice","EP01")
        self.assertFalse(after["ready"])
        self.assertEqual(after["approved_count"],0)
        item=cuts.list_cuts(self.db,"WaitingOffice","EP01")["picture_cuts"][0]
        self.assertFalse(item["source_current"])
        with self.assertRaises(cuts.PictureCutError) as ctx:
            cuts.review_cut(self.db,{
                "project_id":"WaitingOffice","episode_id":"EP01",
                "cut_id":done["cut_id"],"decision":"approve",
                "rationale":"试图批准来源已更改的初剪。"},"owner_picture_test")
        self.assertEqual(ctx.exception.reason,"picture_cut_source_revision_changed")
        with self.assertRaises(cuts.PictureCutError) as ctx:
            cuts.assemble(self.db,"WaitingOffice","EP01",
                          "local_test",runner=self.mock_runner)
        self.assertEqual(ctx.exception.reason,"approved_picture_cut_incomplete")

    def test_ffmpeg_is_never_called_when_any_shot_missing(self):
        with closing(core.open_db(self.db)) as db:
            core.create_shot(db,"WaitingOffice","EP01","02",2,5000)
        with patch.object(cuts.subprocess,"run") as runner:
            with self.assertRaises(cuts.PictureCutError):
                cuts.assemble(self.db,"WaitingOffice","EP01","local_test")
            runner.assert_not_called()

    def test_picture_cut_http_requires_owner_and_video_range(self):
        self.approved_shot()
        result=cuts.assemble(self.db,"WaitingOffice","EP01","local_test",
                             runner=self.mock_runner)
        app=web.StudioServer(str(Path(self.db).with_name("picture-console.sqlite")),
            poller=web.Poller(probe=lambda _:{"ok":False}),
            bind=("127.0.0.1",0))
        app.production_db_path=self.db
        app.identity=sample.MockOwner()
        worker=threading.Thread(target=app.serve_forever,daemon=True)
        worker.start()
        try:
            common={"Host":"127.0.0.1:8900",
                "X-Forwarded-Proto":"https",
                "X-Forwarded-Host":"jipite.borealos.cn",
                "X-Director-Studio-Auth-Mode":"microsoft",
                "Cookie":COOKIE_SID+"="+sample.SID}
            query="?project=WaitingOffice&episode=EP01"
            def get(path,headers=None):
                conn=http.client.HTTPConnection("127.0.0.1",app.server_port,timeout=6)
                conn.request("GET",path,headers={**common,**(headers or {})})
                reply=conn.getresponse()
                status,body=reply.status,reply.read()
                conn.close()
                return status,body
            status,_=get("/api/v1/picture-cuts/readiness"+query,{"Cookie":""})
            self.assertEqual(status,401)
            status,body=get("/api/v1/picture-cuts/readiness"+query)
            self.assertEqual(status,200)
            self.assertTrue(json.loads(body)["ready"])
            file="/api/v1/picture-cuts/file"+query+"&cut="+result["cut_id"]
            self.assertEqual(get(file,{"Cookie":""})[0],401)
            status,body=get(file,{"Range":"bytes=0-13"})
            self.assertEqual(status,206)
            self.assertEqual(len(body),14)
            self.assertEqual(get(file,{"Range":"bytes=9999999-"})[0],416)
            status,body=get("/api/v1/picture-cuts"+query)
            self.assertEqual(status,200)
            self.assertEqual(len(json.loads(body)["picture_cuts"]),1)
        finally:
            app.shutdown();app.server_close();worker.join(timeout=4)


if __name__=="__main__":
    unittest.main()
