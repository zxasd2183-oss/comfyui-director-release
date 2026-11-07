"""Version-bound licensed stereo stems -> owner-reviewed A/V master (CPU only)."""
import base64
from contextlib import closing
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parent))
import production_core as core
import video_results as video
import picture_cuts as picture
import audio_stems as audio
import audio_master as master
import audio_master_jobs as jobs
import studio_server as web
import test_video_handoff_integration as fixture
import test_video_results as take_fixture
import test_picture_cuts as pic_fixture
import test_audio_stems as audio_fixture
from studio_identity import COOKIE_SID


class AVMasterTests(unittest.TestCase):
    upload=fixture.StudioToGpuHandoffTests.upload
    save=fixture.StudioToGpuHandoffTests.save
    review=fixture.StudioToGpuHandoffTests.review
    build_approved_chain=fixture.StudioToGpuHandoffTests.build_approved_chain
    begin=take_fixture.VideoReturnTests.begin
    chunks=take_fixture.VideoReturnTests.chunks
    finish=take_fixture.VideoReturnTests.finish
    review_take_result=take_fixture.VideoReturnTests.review_take_result
    review_video_plan_rejected_then_revised=(
        take_fixture.VideoReturnTests.review_video_plan_rejected_then_revised)

    def setUp(self):
        take_fixture.VideoReturnTests.setUp(self)
        with closing(core.open_db(self.db)) as db:
            video.prepare_schema(db)
            picture.prepare_schema(db)
            audio.prepare_schema(db)
            master.prepare_schema(db)
            jobs.prepare_schema(db)

    @staticmethod
    def fake_master_runner(args,**kwargs):
        if args[0]=="/usr/bin/ffmpeg":
            Path(args[-1]).write_bytes(
                b"\x00\x00\x00\x18ftypisom"+b"M"*1024)
            return type("Output",(),{"returncode":0,"stdout":b""})()
        if args[0]=="/usr/bin/ffprobe":
            return type("Output",(),{"returncode":0,"stdout":json.dumps({
                "format":{"format_name":"mov,mp4,m4a,3gp,3g2,mj2",
                    "duration":"3.0"},
                "streams":[{"codec_type":"video","codec_name":"h264",
                    "width":1080,"height":1920},
                    {"codec_type":"audio","codec_name":"aac",
                     "sample_rate":"48000","channels":2}]}).encode()})()
        raise AssertionError("External call forbidden")

    def approved_picture(self):
        started=self.begin()
        self.chunks(started["upload_id"])
        take=self.finish(started["upload_id"])
        self.review_take_result(take["take_id"])
        pic=picture.assemble(self.db,"WaitingOffice","EP01",
            "local_owner",runner=pic_fixture.PictureCutTests.mock_runner)
        picture.review_cut(self.db,{"project_id":"WaitingOffice",
            "episode_id":"EP01","cut_id":pic["cut_id"],
            "decision":"approve",
            "rationale":"已完整检查镜头顺序、视觉连续性及合成初剪效果。"},
            "local_owner")
        return pic

    def approved_stem(self,kind,rights):
        content=audio_fixture.pcm_wav(duration=3)
        original=hashlib.sha256(content).hexdigest()
        start=audio.start(self.db,{"project_id":"WaitingOffice",
            "episode_id":"EP01","stem":kind,
            "file_sha256":original,"size_bytes":len(content),
            "rights_ref":rights},"audio_owner")
        offset=0
        while offset<len(content):
            part=content[offset:offset+audio.CHUNK_BYTES]
            done=audio.append(self.db,{"upload_id":start["upload_id"],
                "offset":offset,"chunk_base64":base64.b64encode(part).decode()},
                "audio_owner",self.lock)
            offset=done["received_bytes"]
        added=audio.finish(self.db,{"upload_id":start["upload_id"]},
            "audio_owner",self.lock)
        audio.review(self.db,{"project_id":"WaitingOffice",
            "episode_id":"EP01","audio_id":added["audio_id"],
            "decision":"approve","rights_verified":True,
            "rationale":"人工试听音轨与声线许可、音乐和音效授权凭证均已核实。"},
            "audio_owner")
        return added

    def complete(self):
        self.approved_picture()
        for kind in ("dialogue","music","effects"):
            self.approved_stem(kind,"LICENSE-"+kind+"-OWNER-TEST-2026")
        ready=master.readiness(self.db,"WaitingOffice","EP01")
        self.assertTrue(ready["ready"],ready["blocked"])
        return ready

    def review_master(self,uid,rights=True,listened=True,decision="approve"):
        return master.review(self.db,{"project_id":"WaitingOffice",
            "episode_id":"EP01","master_id":uid,"decision":decision,
            "rationale":"人工完整试听整集、核验版权、口型、音量与声画同步。",
            "rights_verified":rights,"final_listen_completed":listened},
            "master_owner")

    def test_missing_stems_picture_and_licensing_block_audio_master(self):
        missing=master.readiness(self.db,"WaitingOffice","EP01")
        self.assertFalse(missing["ready"])
        self.assertIn("current_approved_picture_cut_missing",missing["blocked"])
        self.assertIn("approved_audio_stem_missing:dialogue",missing["blocked"])
        self.approved_picture()
        self.approved_stem("dialogue","LICENSE-VOICE-OWNER-2026")
        blocked=master.readiness(self.db,"WaitingOffice","EP01")
        self.assertFalse(blocked["ready"])
        self.assertEqual(blocked["approved_audio_count"],1)
        with patch.object(master.subprocess,"run") as ffmpeg:
            with self.assertRaises(master.MasterError):
                master.mix(self.db,"WaitingOffice","EP01","owner")
            ffmpeg.assert_not_called()

    def test_approved_3_stems_generate_distinct_audio_video_master(self):
        ready=self.complete()
        called=[]
        def local(args,**kwargs):
            called.append(args)
            return self.fake_master_runner(args,**kwargs)
        result=master.mix(self.db,"WaitingOffice","EP01",
                          "master_owner",runner=local)
        self.assertEqual(result["status"],"in_review")
        self.assertFalse(result["gpu_action"])
        self.assertFalse(result["release_approved"])
        ffmpeg=next(args for args in called if args[0]=="/usr/bin/ffmpeg")
        self.assertIn("amix=inputs=3",ffmpeg[ffmpeg.index("-filter_complex")+1])
        self.assertIn("loudnorm=I=-16",ffmpeg[ffmpeg.index("-filter_complex")+1])
        self.assertEqual(ffmpeg.count("-i"),4)
        self.assertEqual(ffmpeg[ffmpeg.index("-c:v")+1],"copy")
        duplicated=master.mix(self.db,"WaitingOffice","EP01",
            "master_owner",runner=local)
        self.assertTrue(duplicated["already_mixed"])
        self.assertEqual(duplicated["master_id"],result["master_id"])
        self.assertEqual(master.list_masters(self.db,"WaitingOffice","EP01")[
            "masters"][0]["source_manifest_sha256"],
            ready["source_manifest_sha256"])
        with self.assertRaises(master.MasterError) as blocked:
            self.review_master(result["master_id"],listened=False)
        self.assertEqual(blocked.exception.reason,
            "master_manual_sound_rights_review_required")
        reviewed=self.review_master(result["master_id"])
        self.assertEqual(reviewed["status"],"approved")
        with self.assertRaises(master.MasterError):
            self.review_master(result["master_id"])
        with closing(core.open_db(self.db,initialize=False)) as db:
            self.assertTrue(core.verify_chain(db))

    def test_new_audio_revision_invalidates_old_master(self):
        self.complete()
        result=master.mix(self.db,"WaitingOffice","EP01",
            "owner",runner=self.fake_master_runner)
        self.approved_stem("music","REVISED-MUSIC-LICENSE-2026")
        newest=master.readiness(self.db,"WaitingOffice","EP01")
        self.assertTrue(newest["ready"])
        self.assertNotEqual(newest["source_manifest_sha256"],
                            master.list_masters(self.db,"WaitingOffice","EP01")[
                                "masters"][0]["source_manifest_sha256"])
        with self.assertRaises(master.MasterError) as blocked:
            self.review_master(result["master_id"])
        self.assertEqual(blocked.exception.reason,"master_sources_outdated")
        self.assertFalse(master.list_masters(self.db,
            "WaitingOffice","EP01")["masters"][0]["source_current"])

    def test_durable_master_queue_and_restarts(self):
        ready=self.complete()
        request={"project_id":"WaitingOffice","episode_id":"EP01",
            "source_manifest_sha256":ready["source_manifest_sha256"],
            "acknowledge_local_cpu":False}
        with self.assertRaises(jobs.MasterJobError):
            jobs.enqueue(self.db,request,"owner")
        request["acknowledge_local_cpu"]=True
        start=jobs.enqueue(self.db,request,"owner")
        self.assertEqual(start["status"],"queued")
        self.assertTrue(jobs.enqueue(self.db,request,"owner")["existing"])
        done=jobs.process_one(self.db,runner=self.fake_master_runner)
        self.assertTrue(done["ok"])
        self.assertEqual(done["status"],"done")
        self.assertFalse(done["gpu_action"])
        state=jobs.list_jobs(self.db,"WaitingOffice","EP01")["jobs"][0]
        self.assertEqual(state["status"],"done")
        self.assertEqual(state["master_id"],done["master_id"])
        self.assertIsNone(jobs.process_one(self.db))
        with closing(core.open_db(self.db,initialize=False)) as db:
            self.assertTrue(core.verify_chain(db))

    @unittest.skipUnless(Path("/usr/bin/ffmpeg").exists(),
                         "Requires actual ffmpeg")
    def test_real_ffmpeg_mix_pcm_stems_and_video_copy(self):
        original=Path(self.db).parent/"real_master_source.mp4"
        subprocess.run(["/usr/bin/ffmpeg","-nostdin","-hide_banner",
            "-loglevel","error","-f","lavfi","-i",
            "color=c=black:s=1080x1920:r=24:d=3",
            "-c:v","mpeg4","-q:v","8","-pix_fmt","yuv420p",
            "-y",str(original)],check=True,capture_output=True,timeout=60)
        source=original.read_bytes()
        self.payload.update(size_bytes=len(source),
            file_sha256=hashlib.sha256(source).hexdigest())
        start=self.begin()
        offset=0
        while offset<len(source):
            part=source[offset:offset+video.CHUNK_BYTES]
            receipt=video.append_chunk(self.db,{"upload_id":start["upload_id"],
                "offset":offset,"chunk_base64":base64.b64encode(part).decode()},
                take_fixture.OWNER,self.lock)
            offset=receipt["received_bytes"]
        take=video.finish_upload(self.db,{"upload_id":start["upload_id"]},
            take_fixture.OWNER,self.lock)
        self.review_take_result(take["take_id"])
        cut=picture.assemble(self.db,"WaitingOffice","EP01","owner")
        picture.review_cut(self.db,{"project_id":"WaitingOffice",
            "episode_id":"EP01","cut_id":cut["cut_id"],"decision":"approve",
            "rationale":"完整复核真实 FFmpeg 初剪与素材来源。"},"owner")
        for kind in ("dialogue","music","effects"):
            self.approved_stem(kind,"REAL-TEST-RIGHTS-"+kind+"-2026")
        mixed=master.mix(self.db,"WaitingOffice","EP01","owner")
        self.assertEqual(mixed["status"],"in_review")
        path,size=master.get_file(self.db,"WaitingOffice","EP01",
            mixed["master_id"])
        self.assertGreater(size,128)
        result=master._probe_mp4(path,subprocess.run)
        self.assertAlmostEqual(result["duration_seconds"],3.,delta=.35)
        self.assertEqual(result["width"],1080)
        self.assertEqual(result["height"],1920)


if __name__=="__main__":
    unittest.main()
