"""Private subtitle mux release candidate, explicit final QC, no publication."""
import hashlib
import json
import subprocess
from contextlib import closing
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parent))
import production_core as core
import picture_cuts as picture
import video_results as video
import audio_stems as audio
import audio_master as master
import audio_master_jobs as master_jobs
import subtitle_tracks as subtitles
import release_candidates as release
import release_jobs as jobs
import test_video_handoff_integration as fixture
import test_video_results as take_fixture
import test_audio_master as master_fixture
import test_subtitle_tracks as subtitle_fixture


class ReleaseTests(unittest.TestCase):
    upload=fixture.StudioToGpuHandoffTests.upload
    save=fixture.StudioToGpuHandoffTests.save
    review=fixture.StudioToGpuHandoffTests.review
    build_approved_chain=fixture.StudioToGpuHandoffTests.build_approved_chain
    begin=take_fixture.VideoReturnTests.begin
    chunks=take_fixture.VideoReturnTests.chunks
    finish=take_fixture.VideoReturnTests.finish
    review_take_result=take_fixture.VideoReturnTests.review_take_result
    approved_picture=master_fixture.AVMasterTests.approved_picture
    approved_stem=master_fixture.AVMasterTests.approved_stem
    complete=master_fixture.AVMasterTests.complete

    def setUp(self):
        master_fixture.AVMasterTests.setUp(self)
        with closing(core.open_db(self.db)) as db:
            subtitles.prepare_schema(db)
            release.prepare_schema(db)
            jobs.prepare_schema(db)

    @staticmethod
    def fake_mux(args,**kwargs):
        if args[0]=="/usr/bin/ffmpeg":
            Path(args[-1]).write_bytes(
                b"\x00\x00\x00\x18ftypisom"+b"R"*1024)
            return type("Output",(),{"returncode":0,"stdout":b""})()
        if args[0]=="/usr/bin/ffprobe":
            return type("Output",(),{"returncode":0,"stdout":json.dumps({
                "format":{"format_name":"mov,mp4,m4a,3gp,3g2,mj2",
                    "duration":"3.0"},
                "streams":[{"codec_type":"video","codec_name":"mpeg4",
                            "width":1080,"height":1920},
                           {"codec_type":"audio","codec_name":"aac"},
                           {"codec_type":"subtitle","codec_name":"mov_text"}]
                }).encode()})()
        raise AssertionError("unexpected program")

    def subtitle(self,text=subtitle_fixture.SRT):
        created=subtitles.save(self.db,{
            "project_id":"WaitingOffice","episode_id":"EP01",
            "language":"zh-CN","text":text,
            "source_ref":"SCRIPT-EP01-OWNER-TRANSLATION-2026"},"subtitle_owner")
        subtitles.review(self.db,{"project_id":"WaitingOffice",
            "episode_id":"EP01","subtitle_id":created["subtitle_id"],
            "decision":"approve","rationale":"已逐句核对字幕来源、授权和时长范围。",
            "text_rights_verified":True},"subtitle_owner")
        return created["subtitle_id"]

    def sound(self):
        self.complete()
        created=master.mix(self.db,"WaitingOffice","EP01",
            "master_owner",runner=master_fixture.AVMasterTests.fake_master_runner)
        master.review(self.db,{"project_id":"WaitingOffice",
            "episode_id":"EP01","master_id":created["master_id"],
            "decision":"approve",
            "rationale":"已完整试听和确认合成版本来源及音画同步。",
            "rights_verified":True,"final_listen_completed":True},
            "master_owner")
        return created["master_id"]

    def ready(self):
        uid=self.sound()
        sub=self.subtitle()
        r=release.readiness(self.db,"WaitingOffice","EP01")
        self.assertTrue(r["ready"],r["blocked"])
        return r,uid,sub

    def approve(self,uid,checks=True):
        return release.review(self.db,{
            "project_id":"WaitingOffice","episode_id":"EP01",
            "release_id":uid,"decision":"approve",
            "rationale":"已完成画面、对白、配乐、字幕、版权凭证和全片播放终审。",
            "all_media_checked":checks,"subtitle_checked":checks,
            "rights_checked":checks,"final_playback_checked":checks},
            "release_owner")

    def test_unapproved_audio_and_subtitle_block_release(self):
        r=release.readiness(self.db,"WaitingOffice","EP01")
        self.assertFalse(r["ready"])
        self.assertIn("current_av_master_not_approved",r["blocked"])
        self.assertIn("chinese_subtitles_missing",r["blocked"])
        self.sound()
        r=release.readiness(self.db,"WaitingOffice","EP01")
        self.assertEqual(r["blocked"],["chinese_subtitles_missing"])
        with self.assertRaises(release.ReleaseError) as blocked:
            release.mux(self.db,"WaitingOffice","EP01","release_owner")
        self.assertEqual(blocked.exception.reason,"release_sources_not_approved")

    def test_subtitle_mux_locks_current_sources_and_requires_manual_final_qc(self):
        ready,master_id,sub_id=self.ready()
        calls=[]
        def fake(args,**kwargs):
            calls.append(args)
            return self.fake_mux(args,**kwargs)
        generated=release.mux(self.db,"WaitingOffice","EP01",
                              "release_owner",runner=fake)
        self.assertEqual(generated["status"],"in_review")
        self.assertFalse(generated["publicly_released"])
        ffmpeg=next(a for a in calls if a[0]=="/usr/bin/ffmpeg")
        self.assertEqual(ffmpeg[ffmpeg.index("-c:v")+1],"copy")
        self.assertEqual(ffmpeg[ffmpeg.index("-c:a")+1],"copy")
        self.assertEqual(ffmpeg[ffmpeg.index("-c:s")+1],"mov_text")
        self.assertEqual(ffmpeg.count("-i"),2)
        again=release.mux(self.db,"WaitingOffice","EP01",
                          "release_owner",runner=fake)
        self.assertTrue(again["already_muxed"])
        self.assertEqual(again["release_id"],generated["release_id"])
        with self.assertRaises(release.ReleaseError) as incomplete:
            self.approve(generated["release_id"],checks=False)
        self.assertEqual(incomplete.exception.reason,
            "release_final_qc_confirmation_required")
        completed=self.approve(generated["release_id"])
        self.assertEqual(completed["status"],"approved")
        self.assertFalse(completed["publicly_released"])
        with self.assertRaises(release.ReleaseError):
            self.approve(generated["release_id"])
        with closing(core.open_db(self.db,initialize=False)) as db:
            self.assertTrue(core.verify_chain(db))

    def test_revised_subtitle_invalidates_candidate(self):
        self.ready()
        candidate=release.mux(self.db,"WaitingOffice","EP01",
                              "release_owner",runner=self.fake_mux)
        self.subtitle(text=subtitle_fixture.SRT.replace("大家好","早上好"))
        after=release.readiness(self.db,"WaitingOffice","EP01")
        self.assertTrue(after["ready"])
        self.assertFalse(release.list_candidates(self.db,
            "WaitingOffice","EP01")["candidates"][0]["source_current"])
        with self.assertRaises(release.ReleaseError) as stale:
            self.approve(candidate["release_id"])
        self.assertEqual(stale.exception.reason,"release_sources_outdated")

    def test_serial_release_queue_and_manifest_hash_gate(self):
        ready,_,_=self.ready()
        fields={"project_id":"WaitingOffice","episode_id":"EP01",
            "source_manifest_sha256":ready["source_manifest_sha256"],
            "acknowledge_local_cpu":False}
        with self.assertRaises(jobs.ReleaseJobError):
            jobs.enqueue(self.db,fields,"release_owner")
        fields["acknowledge_local_cpu"]=True
        job=jobs.enqueue(self.db,fields,"release_owner")
        self.assertEqual(job["status"],"queued")
        self.assertTrue(jobs.enqueue(self.db,fields,"release_owner")["existing"])
        done=jobs.process_one(self.db,runner=self.fake_mux)
        self.assertEqual(done["status"],"done")
        self.assertFalse(done["gpu_action"])
        self.assertIsNone(jobs.process_one(self.db))
        listed=jobs.list_jobs(self.db,"WaitingOffice","EP01")["jobs"]
        self.assertEqual(listed[0]["release_id"],done["release_id"])
        self.assertEqual(listed[0]["attempts"],1)

    @unittest.skipUnless(Path("/usr/bin/ffmpeg").exists() and
                         Path("/usr/bin/ffprobe").exists(),
                         "requires real ffmpeg")
    def test_real_ffmpeg_embeds_subtitle_stream_without_transcoding_av(self):
        # The audio mix pipeline already has an independent real-FFmpeg test.
        # Here a disposable, compliant A/V fixture tests actual mov_text mux.
        self.complete()
        movie=Path(self.db).parent/"eligible-audio-video.mp4"
        subprocess.run(["/usr/bin/ffmpeg","-nostdin","-hide_banner",
            "-loglevel","error","-f","lavfi","-i",
            "color=c=blue:s=64x64:r=24:d=3",
            "-f","lavfi","-i","anullsrc=r=48000:cl=stereo",
            "-t","3","-c:v","mpeg4","-q:v","5",
            "-c:a","aac","-b:a","128k","-y",str(movie)],
            check=True,capture_output=True,timeout=30)
        approved=master.readiness(self.db,"WaitingOffice","EP01")
        master_id="MASTER_"+"a"*32
        digest=hashlib.sha256(movie.read_bytes()).hexdigest()
        dest=master._store(self.db,create=True)/(master_id+".mp4")
        dest.write_bytes(movie.read_bytes())
        with closing(core.open_db(self.db)) as db:
            with core.transaction(db):
                db.execute("INSERT INTO studio_av_masters("
                    "master_id,project_id,episode_id,source_manifest_sha256,"
                    "source_manifest_json,file_sha256,size_bytes,"
                    "duration_seconds,status,created_at,reviewer) "
                    "VALUES(?,?,?,?,?,?,?,?,'approved',1,'fixture_reviewer')",
                    (master_id,"WaitingOffice","EP01",
                     approved["source_manifest_sha256"],
                     json.dumps(approved["source_manifest"]),digest,
                     movie.stat().st_size,3.0))
                core._audit(db,"fixture_reviewer","av.master_fixture",master_id,
                    {"source_sha256":approved["source_manifest_sha256"]})
        self.subtitle()
        ready=release.readiness(self.db,"WaitingOffice","EP01")
        self.assertTrue(ready["ready"],ready["blocked"])
        result=release.mux(self.db,"WaitingOffice","EP01","owner")
        path,size=release.get_file(self.db,"WaitingOffice","EP01",
                                   result["release_id"])
        self.assertGreater(size,128)
        meta=release._probe(path,subprocess.run)
        self.assertAlmostEqual(meta["duration_seconds"],3.,delta=.35)
        self.assertFalse(result["publicly_released"])


if __name__=="__main__":
    unittest.main()
