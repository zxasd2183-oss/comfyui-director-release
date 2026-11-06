"""Video return and approval integration tests; no GPU/network required."""
import base64
import hashlib
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
import test_video_handoff_integration as fixture
import video_results as vr
import studio_server as server
from studio_identity import COOKIE_SID

MP4=b"\x00\x00\x00\x18ftypisom"+b"X"*(4096-12)
FPS={"width":1080,"height":1920,"fps":24.,
     "duration_seconds":3.,"codec":"h264"}
OWNER="studio_video_owner_approval"
CSRF="test_owner_video_csrf"
SID="s"*43


class MockOwner:
    def check(self,sid):
        return {"sub":OWNER,"csrf":CSRF} if sid==SID else None


class VideoReturnTests(unittest.TestCase):
    upload=fixture.StudioToGpuHandoffTests.upload
    save=fixture.StudioToGpuHandoffTests.save
    review=fixture.StudioToGpuHandoffTests.review
    build_approved_chain=fixture.StudioToGpuHandoffTests.build_approved_chain

    def setUp(self):
        fixture.StudioToGpuHandoffTests.setUp(self)
        self.build_approved_chain()
        self.package=fixture.work.get_video_handoff_package(
            self.db,"WaitingOffice","EP01","01")
        self.sha=hashlib.sha256(MP4).hexdigest()
        self.payload={
            "project_id":"WaitingOffice","episode_id":"EP01",
            "shot_id":"01","plan_revision":1,
            "package_sha256":self.package["package_sha256"],
            "file_sha256":self.sha,"size_bytes":len(MP4),
            "prompt_id":"12345678-1234-1234-1234-123456789abc"}
        self.lock=threading.Lock()

    def begin(self,actor=OWNER):
        return vr.begin_upload(self.db,self.payload,actor)

    def chunks(self,uid,actor=OWNER):
        offset=0
        while offset<len(MP4):
            chunk=MP4[offset:offset+900]
            result=vr.append_chunk(self.db,{
                "upload_id":uid,"offset":offset,
                "chunk_base64":base64.b64encode(chunk).decode()
            },actor,self.lock)
            offset=result["received_bytes"]
        return offset

    def finish(self,uid,actor=OWNER):
        with patch.object(vr,"probe_video",return_value=FPS):
            return vr.finish_upload(self.db,{"upload_id":uid},actor,self.lock)

    def review_take_result(self,take,decision="approve",reason="导演已核对视频与计划，确认本镜头连续性及音画质量。"):
        return vr.review_take(self.db,{
            "project_id":"WaitingOffice","episode_id":"EP01","shot_id":"01",
            "take_id":take,"decision":decision,"rationale":reason},OWNER)

    def test_resume_checks_chunks_and_preserves_real_media(self):
        original=self.begin()
        uid=original["upload_id"]
        self.assertEqual(original["received_bytes"],0)
        first=vr.append_chunk(self.db,{"upload_id":uid,"offset":0,
            "chunk_base64":base64.b64encode(MP4[:1024]).decode()},OWNER,self.lock)
        self.assertEqual(first["received_bytes"],1024)
        resumed=self.begin()
        self.assertTrue(resumed["resumed"])
        self.assertEqual(resumed["upload_id"],uid)
        self.assertEqual(resumed["received_bytes"],1024)
        with self.assertRaises(vr.VideoResultError) as ctx:
            vr.append_chunk(self.db,{"upload_id":uid,"offset":0,
                "chunk_base64":base64.b64encode(b"AAAA").decode()},OWNER,self.lock)
        self.assertEqual(ctx.exception.reason,"video_upload_offset_conflict")
        with self.assertRaises(vr.VideoResultError) as ctx:
            vr.append_chunk(self.db,{"upload_id":uid,"offset":1024,
                "chunk_base64":base64.b64encode(MP4[1024:]).decode()},
                "different_owner",self.lock)
        self.assertEqual(ctx.exception.status,404)
        vr.append_chunk(self.db,{"upload_id":uid,"offset":1024,
            "chunk_base64":base64.b64encode(MP4[1024:]).decode()},OWNER,self.lock)
        take=self.finish(uid)
        self.assertEqual(take["status"],"in_review")
        self.assertFalse(take["gpu_action"])
        self.assertEqual(take["media_sha256"],self.sha)
        path,size=vr.get_take_file(self.db,"WaitingOffice","EP01","01",take["take_id"])
        self.assertEqual(size,len(MP4))
        self.assertEqual(path.read_bytes(),MP4)
        listed=vr.list_takes(self.db,"WaitingOffice","EP01","01")["takes"]
        self.assertEqual(len(listed),1)
        self.assertEqual(listed[0]["status"],"in_review")
        before=fixture.work.get_episode_readiness(self.db,"WaitingOffice","EP01")
        self.assertEqual(before["approved_take_count"],0)
        self.assertEqual(before["shots"][0]["video_take_status"],"in_review")
        pending=fixture.work.list_reviews(self.db,"WaitingOffice","EP01")["pending"]
        self.assertEqual([x["unit_id"] for x in pending
            if x["kind"]=="video_take"],[take["take_id"]])
        with self.assertRaises(vr.VideoResultError):
            vr.get_take_file(self.db,"WaitingOffice","EP01","02",take["take_id"])
        good=self.review_take_result(take["take_id"])
        self.assertEqual(good["status"],"approved")
        complete=fixture.work.get_episode_readiness(self.db,"WaitingOffice","EP01")
        self.assertEqual(complete["approved_take_count"],1)
        self.assertEqual(complete["shots"][0]["video_take_status"],"approved")
        after=fixture.work.list_reviews(self.db,"WaitingOffice","EP01")["pending"]
        self.assertFalse(any(item["kind"]=="video_take" for item in after))
        with self.assertRaises(vr.VideoResultError) as caught:
            self.review_take_result(take["take_id"])
        self.assertEqual(caught.exception.reason,"video_take_already_reviewed")
        with fixture.closing(fixture.core.open_db(self.db,initialize=False)) as db:
            self.assertTrue(fixture.core.verify_chain(db))

    def test_stale_inputs_or_damaged_files_are_not_approved(self):
        started=self.begin()
        self.chunks(started["upload_id"])
        with patch.object(vr,"probe_video",return_value={
            **FPS,"width":1024}):
            with self.assertRaises(vr.VideoResultError) as ctx:
                vr.finish_upload(self.db,{"upload_id":started["upload_id"]},
                    OWNER,self.lock)
        self.assertEqual(ctx.exception.reason,"video_does_not_match_approved_spec")
        self.assertFalse(vr.list_takes(
            self.db,"WaitingOffice","EP01","01")["takes"])
        take=self.finish(started["upload_id"])
        # Once the underlying approved upstream changes, old render may still
        # be viewed but cannot be newly promoted to approved.
        self.review_video_plan_rejected_then_revised()
        with self.assertRaises(vr.VideoResultError) as caught:
            self.review_take_result(take["take_id"])
        self.assertEqual(caught.exception.reason,"video_source_revision_changed")
        stale=fixture.work.get_episode_readiness(self.db,"WaitingOffice","EP01")
        self.assertEqual(stale["approved_take_count"],0)
        self.assertEqual(stale["shots"][0]["video_take_status"],"stale")

    def review_video_plan_rejected_then_revised(self):
        fixture.work.review_unit(self.db,{
            "project_id":"WaitingOffice","episode_id":"EP01",
            "kind":"video_plans","unit_id":"01","expected_revision":1,
            "decision":"reject","rationale":"视频制作计划需要重新修订版本。"},OWNER)
        self.save("video_plans",{
            "model":"H3 API workflow","prompt":"改进后原始镜头",
            "fps":"24","width":"1080","height":"1920",
            "duration":"3","seed":"1234"},revision=1)
        self.review("video_plans","submit",revision=2)

    def test_tampered_sha_and_wrong_owner_rejected(self):
        self.payload["file_sha256"]="0"*64
        started=self.begin()
        self.chunks(started["upload_id"])
        with self.assertRaises(vr.VideoResultError) as caught:
            self.finish(started["upload_id"])
        self.assertEqual(caught.exception.reason,"video_file_checksum_mismatch")
        self.assertFalse(vr.list_takes(
            self.db,"WaitingOffice","EP01","01")["takes"])

    def test_http_owner_can_upload_resume_and_review_video(self):
        app=server.StudioServer(str(Path(self.db).with_name("http.sqlite")),
            poller=server.Poller(probe=lambda _:{"ok":False}),
            bind=("127.0.0.1",0))
        app.production_db_path=self.db
        app.identity=MockOwner()
        worker=threading.Thread(target=app.serve_forever,daemon=True)
        worker.start()
        try:
            headers={"Host":"127.0.0.1:8900",
                "X-Forwarded-Proto":"https",
                "X-Forwarded-Host":"jipite.borealos.cn",
                "X-Director-Studio-Auth-Mode":"microsoft",
                "Cookie":COOKIE_SID+"="+SID,
                "Origin":"https://jipite.borealos.cn",
                "Content-Type":"application/json"}
            def request(endpoint,payload,header_overrides=None):
                conn=http.client.HTTPConnection("127.0.0.1",app.server_port,timeout=6)
                conn.request("POST","/api/v1/video-results/"+endpoint,
                    body=json.dumps({"csrf":CSRF,**payload}).encode(),
                    headers={**headers,**(header_overrides or {})})
                res=conn.getresponse()
                status=res.status
                value=json.loads(res.read())
                conn.close()
                return status,value
            status,created=request("start",self.payload)
            self.assertEqual(status,200,created)
            uid=created["upload_id"]
            status,received=request("chunk",{
                "upload_id":uid,"offset":0,
                "chunk_base64":base64.b64encode(MP4[:512]).decode()})
            self.assertEqual(status,200,received)
            self.assertEqual(received["received_bytes"],512)
            status,resumed=request("start",self.payload)
            self.assertEqual(status,200,resumed)
            self.assertEqual(resumed["received_bytes"],512)
            status,_=request("chunk",{
                "upload_id":uid,"offset":512,
                "chunk_base64":base64.b64encode(MP4[512:]).decode()},
                {"Cookie":""})
            self.assertEqual(status,401)
            status,received=request("chunk",{
                "upload_id":uid,"offset":512,
                "chunk_base64":base64.b64encode(MP4[512:]).decode()})
            self.assertEqual(status,200,received)
            with patch.object(vr,"probe_video",return_value=FPS):
                status,finished=request("finish",{"upload_id":uid})
            self.assertEqual(status,200,finished)
            self.assertEqual(finished["status"],"in_review")
            status,reviewed=request("review",{
                "project_id":"WaitingOffice","episode_id":"EP01",
                "shot_id":"01","take_id":finished["take_id"],
                "decision":"approve",
                "rationale":"已观看视频并核对真实画面规格、人物连贯性和镜头时长。"})
            self.assertEqual(status,200,reviewed)
            self.assertEqual(reviewed["status"],"approved")
            self.assertEqual(vr.list_takes(self.db,"WaitingOffice","EP01","01")[
                "takes"][0]["status"],"approved")
        finally:
            app.shutdown()
            app.server_close()
            worker.join(timeout=4)

    def test_mp4_http_owner_scope_and_range(self):
        started=self.begin()
        self.chunks(started["upload_id"])
        take=self.finish(started["upload_id"])
        app=server.StudioServer(str(Path(self.db).with_name("console.sqlite")),
            poller=server.Poller(probe=lambda _:{"ok":False}),
            bind=("127.0.0.1",0))
        app.production_db_path=self.db
        app.identity=MockOwner()
        worker=threading.Thread(target=app.serve_forever,daemon=True)
        worker.start()
        try:
            query="?project=WaitingOffice&episode=EP01&shot=01"
            url="/api/v1/video-results/file"+query+"&take="+take["take_id"]
            def get(path, headers=None):
                conn=http.client.HTTPConnection("127.0.0.1",app.server_port,timeout=6)
                default={"Host":"127.0.0.1:8900",
                    "X-Forwarded-Proto":"https",
                    "X-Forwarded-Host":"jipite.borealos.cn",
                    "X-Director-Studio-Auth-Mode":"microsoft",
                    "Cookie":COOKIE_SID+"="+SID}
                conn.request("GET",path,headers={**default,**(headers or {})})
                response=conn.getresponse()
                status,response_headers,content=response.status,dict(response.getheaders()),response.read()
                conn.close()
                return status,response_headers,content
            self.assertEqual(get(url,{"Cookie":""})[0],401)
            status,headers,content=get(url,{"Range":"bytes=0-29"})
            self.assertEqual(status,206)
            self.assertEqual(content,MP4[:30])
            self.assertEqual(headers["Content-Range"],"bytes 0-29/4096")
            self.assertEqual(get(url,{"Range":"bytes=99999-"})[0],416)
            self.assertEqual(get(url.replace("shot=01","shot=02"))[0],404)
            status,headers,content=get("/api/v1/video-results"+query)
            self.assertEqual(status,200)
            self.assertEqual(json.loads(content)["takes"][0]["take_id"],take["take_id"])
            # Illegal POSTs without owner auth must never append media.
            conn=http.client.HTTPConnection("127.0.0.1",app.server_port,timeout=6)
            conn.request("POST","/api/v1/video-results/start",body="{}",
                headers={"Host":"127.0.0.1:8900",
                    "X-Forwarded-Proto":"https",
                    "X-Forwarded-Host":"jipite.borealos.cn",
                    "X-Director-Studio-Auth-Mode":"microsoft",
                    "Origin":"https://jipite.borealos.cn",
                    "Content-Type":"application/json"})
            self.assertEqual(conn.getresponse().status,401)
            conn.close()
        finally:
            app.shutdown()
            app.server_close()
            worker.join(timeout=4)
