"""SRT timing, immutable versions, user rights approval and HTTP isolation."""
from contextlib import closing
import hashlib
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parent))
import production_core as core
import subtitle_tracks as subtitles
import studio_server as server
import test_video_handoff_integration as fixture
import test_video_results as session_fixture
from studio_identity import COOKIE_SID


SRT=("1\n00:00:00,000 --> 00:00:01,100\n大家好。\n\n"
     "2\n00:00:01,300 --> 00:00:02,950\n欢迎来到事务所。\n")


class SubtitleTrackTests(unittest.TestCase):
    def setUp(self):
        fixture.StudioToGpuHandoffTests.setUp(self)
        with closing(core.open_db(self.db)) as db:
            subtitles.prepare_schema(db)
        self.record={"project_id":"WaitingOffice","episode_id":"EP01",
            "language":"zh-CN","text":SRT,
            "source_ref":"SCRIPT-EP01-DIALOGUE-OWNER-2026"}
        self.actor="subtitle_owner"
    
    def save(self):
        return subtitles.save(self.db,self.record,self.actor)

    def approve(self,uid,verified=True,decision="approve"):
        return subtitles.review(self.db,{
            "project_id":"WaitingOffice","episode_id":"EP01",
            "subtitle_id":uid,"decision":decision,
            "rationale":"已逐条核对台词、时间轴、人物口型和字幕使用授权。",
            "text_rights_verified":verified},self.actor)

    def test_srt_is_versioned_and_requires_source_rights_review(self):
        created=self.save()
        self.assertEqual(created["revision"],1)
        self.assertEqual(created["cue_count"],2)
        self.assertFalse(created["gpu_action"])
        file=subtitles.get_file(self.db,"WaitingOffice","EP01",
                                created["subtitle_id"])
        self.assertEqual(file.read_text(),SRT)
        reused=self.save()
        self.assertTrue(reused["already_imported"])
        self.assertEqual(reused["subtitle_id"],created["subtitle_id"])
        with self.assertRaises(subtitles.SubtitleError) as rejected:
            self.approve(created["subtitle_id"],False)
        self.assertEqual(rejected.exception.reason,
            "subtitle_text_rights_verification_required")
        approved=self.approve(created["subtitle_id"])
        self.assertEqual(approved["status"],"approved")
        with self.assertRaises(subtitles.SubtitleError) as twice:
            self.approve(created["subtitle_id"])
        self.assertEqual(twice.exception.reason,"subtitle_already_reviewed")
        self.record["text"]=(SRT.replace("欢迎来到事务所","请到前台登记"))
        second=self.save()
        self.assertEqual(second["revision"],2)
        items=subtitles.list_tracks(self.db,"WaitingOffice","EP01")["subtitles"]
        self.assertEqual(len(items),2)
        old=next(x for x in items if x["subtitle_id"]==created["subtitle_id"])
        self.assertFalse(old["source_current"])
        self.assertTrue(next(x for x in items if x["subtitle_id"]==
            second["subtitle_id"])["source_current"])
        self.record["text"]=SRT
        reverted=self.save()
        self.assertEqual(reverted["revision"],3)
        self.assertNotEqual(reverted["subtitle_id"],created["subtitle_id"])
        self.assertEqual(self.approve(reverted["subtitle_id"])["status"],"approved")
        with closing(core.open_db(self.db,initialize=False)) as db:
            self.assertTrue(core.verify_chain(db))

    def test_srt_strict_sequence_window_overlap_and_markup(self):
        cases=[
            SRT.replace("00:00:02,950","00:00:05,000"),
            SRT.replace("00:00:01,300","00:00:00,500"),
            SRT.replace("2\n00:00:01","5\n00:00:01"),
            SRT.replace("00:00:01,300 -->","00:00:01,300 =>"),
            SRT.replace("大家好。","<script>alert(1)</script>"),
            SRT.replace("大家好。",""),
            SRT.replace("00:00:02,950","00:00:02,950")+"\n\n"
                 "3\n00:00:02,960 --> 00:00:04,000\n字幕溢出。",
        ]
        for text in cases:
            with self.subTest(payload=text[:30]):
                self.record["text"]=text
                with self.assertRaises(subtitles.SubtitleError):
                    self.save()
        self.record["text"]=SRT
        self.record["source_ref"]=""
        with self.assertRaises(subtitles.SubtitleError):
            self.save()
        self.record["source_ref"]="SCRIPT-EP01-DIALOGUE-OWNER-2026"
        self.record["language"]="../zh-CN"
        with self.assertRaises(subtitles.SubtitleError):
            self.save()

    def test_old_pending_caption_version_cannot_be_approved(self):
        first=self.save()
        self.record["text"]=SRT.replace("大家好。","早上好。")
        second=self.save()
        with self.assertRaises(subtitles.SubtitleError) as stale:
            self.approve(first["subtitle_id"])
        self.assertEqual(stale.exception.reason,"subtitle_revision_stale")
        self.assertEqual(self.approve(second["subtitle_id"])["status"],"approved")

    def test_webvtt_preview_has_safe_timestamps_and_no_html(self):
        converted=subtitles.as_webvtt(SRT)
        self.assertTrue(converted.startswith("WEBVTT\\n\\n".replace("\\n","\n")))
        self.assertIn("00:00:00.000 --> 00:00:01.100",converted)
        self.assertIn("欢迎来到事务所。",converted)
        self.assertNotIn("<script>",converted)
        with self.assertRaises(subtitles.SubtitleError):
            subtitles.as_webvtt(SRT.replace("00:00:01,300",
                                            "00:00:01,X00"))

    def test_subtitle_http_never_exposes_private_text_anonymously(self):
        created=self.save()
        app=server.StudioServer(str(Path(self.db).with_name("srt-http.sqlite")),
            poller=server.Poller(probe=lambda _:{"ok":False}),
            bind=("127.0.0.1",0))
        app.production_db_path=self.db
        app.identity=session_fixture.MockOwner()
        worker=threading.Thread(target=app.serve_forever,daemon=True)
        worker.start()
        try:
            common={"Host":"127.0.0.1:8900",
                "X-Forwarded-Proto":"https",
                "X-Forwarded-Host":"jipite.borealos.cn",
                "X-Director-Studio-Auth-Mode":"microsoft",
                "Origin":"https://jipite.borealos.cn",
                "Cookie":COOKIE_SID+"="+session_fixture.SID}
            def req(method,path,payload=None,header=None):
                conn=http.client.HTTPConnection("127.0.0.1",
                    app.server_port,timeout=7)
                h={**common,**(header or {})}
                if payload is not None:h["Content-Type"]="application/json"
                conn.request(method,path,headers=h,
                    body=json.dumps(payload).encode() if payload is not None else None)
                resp=conn.getresponse()
                result=(resp.status,json.loads(resp.read()))
                conn.close()
                return result
            q="?project=WaitingOffice&episode=EP01"
            item="/api/v1/subtitles/file"+q+"&subtitle="+created["subtitle_id"]
            self.assertEqual(req("GET",item,header={"Cookie":""})[0],401)
            status,payload=req("GET",item)
            self.assertEqual(status,200)
            self.assertEqual(payload["text"],SRT)
            self.assertEqual(req("GET","/api/v1/subtitles"+q)[0],200)
            conn=http.client.HTTPConnection("127.0.0.1",app.server_port,timeout=7)
            conn.request("GET","/api/v1/subtitles/vtt"+q+
                "&subtitle="+created["subtitle_id"],headers=common)
            resp=conn.getresponse()
            self.assertEqual(resp.status,200)
            self.assertIn("text/vtt",resp.getheader("Content-Type"))
            self.assertTrue(resp.read().decode().startswith("WEBVTT"))
            conn.close()
            data={"csrf":session_fixture.CSRF,
                "project_id":"WaitingOffice","episode_id":"EP01",
                "subtitle_id":created["subtitle_id"],"decision":"approve",
                "rationale":"对照正式台词核对了字幕并取得文字使用授权。",
                "text_rights_verified":True}
            self.assertEqual(req("POST","/api/v1/subtitles/review",
                data,header={"Cookie":""})[0],401)
            self.assertEqual(req("POST","/api/v1/subtitles/review",
                {**data,"csrf":"wrong"})[0],403)
            self.assertEqual(req("POST","/api/v1/subtitles/review",data)[0],200)
        finally:
            app.shutdown();app.server_close();worker.join(timeout=5)


if __name__=="__main__":
    unittest.main()
