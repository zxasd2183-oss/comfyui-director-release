"""Real WAV intake/rights review over owner HTTP; no GPU or fake audio."""
import base64
from contextlib import closing
import hashlib
import http.client
import io
import json
from pathlib import Path
import struct
import sys
import threading
import unittest
import wave
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parent))
import audio_stems as audio
import production_core as core
import studio_server as server
import test_video_results as fixture
from studio_identity import COOKIE_SID


def pcm_wav(duration=3,rate=48000,channels=2):
    buffer=io.BytesIO()
    with wave.open(buffer,"wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(2)
        file.setframerate(rate)
        # Silence is intentionally a self-generated fixture, NOT a film mix.
        file.writeframes(b"\x00"*(duration*rate*channels*2))
    return buffer.getvalue()


class AudioStemsTests(unittest.TestCase):
    def setUp(self):
        fixture.VideoReturnTests.setUp(self)
        self.lock=threading.Lock()
        self.content=pcm_wav()
        self.sha=hashlib.sha256(self.content).hexdigest()
        self.data={"project_id":"WaitingOffice","episode_id":"EP01",
            "stem":"dialogue","size_bytes":len(self.content),
            "file_sha256":self.sha,
            "rights_ref":"OWN-VOICE-TEST-01 — recording owned and consent documented"}
        with closing(core.open_db(self.db)) as db:
            audio.prepare_schema(db)

    def start(self,actor=fixture.OWNER):
        return audio.start(self.db,self.data,actor)

    def upload(self,uid,actor=fixture.OWNER):
        current=0
        while current<len(self.content):
            part=self.content[current:current+audio.CHUNK_BYTES]
            result=audio.append(self.db,{"upload_id":uid,"offset":current,
                "chunk_base64":base64.b64encode(part).decode()},actor,self.lock)
            current=result["received_bytes"]
        return current

    def finish(self,uid,actor=fixture.OWNER):
        return audio.finish(self.db,{"upload_id":uid},actor,self.lock)

    def approve(self,uid,verify=True,decision="approve"):
        return audio.review(self.db,{"project_id":"WaitingOffice",
            "episode_id":"EP01","audio_id":uid,"decision":decision,
            "rationale":"人工完整试听对白并核对音轨质量、同步和授权来源。",
            "rights_verified":verify},fixture.OWNER)

    def test_real_wav_upload_resume_review_and_immutable_versions(self):
        created=self.start()
        uid=created["upload_id"]
        part=self.content[:250000]
        res=audio.append(self.db,{"upload_id":uid,"offset":0,
            "chunk_base64":base64.b64encode(part).decode()},
            fixture.OWNER,self.lock)
        self.assertEqual(res["received_bytes"],len(part))
        resumed=self.start()
        self.assertEqual(resumed["upload_id"],uid)
        self.assertEqual(resumed["received_bytes"],len(part))
        with self.assertRaises(audio.AudioError) as wrong:
            audio.append(self.db,{"upload_id":uid,"offset":0,
                "chunk_base64":base64.b64encode(b"AAAA").decode()},
                fixture.OWNER,self.lock)
        self.assertEqual(wrong.exception.reason,"audio_upload_offset_conflict")
        with self.assertRaises(audio.AudioError) as wrong:
            audio.append(self.db,{"upload_id":uid,"offset":len(part),
                "chunk_base64":base64.b64encode(b"AAAA").decode()},
                "another_user",self.lock)
        self.assertEqual(wrong.exception.status,404)
        audio.append(self.db,{"upload_id":uid,"offset":len(part),
            "chunk_base64":base64.b64encode(self.content[len(part):]).decode()},
            fixture.OWNER,self.lock)
        finished=self.finish(uid)
        self.assertEqual(finished["status"],"in_review")
        self.assertFalse(finished["gpu_action"])
        file,size=audio.get_stem_file(self.db,"WaitingOffice","EP01",
            finished["audio_id"])
        self.assertEqual(size,len(self.content))
        self.assertEqual(file.read_bytes(),self.content)
        items=audio.list_stems(self.db,"WaitingOffice","EP01")["tracks"]
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]["revision"],1)
        self.assertTrue(items[0]["source_current"])
        with self.assertRaises(audio.AudioError) as wrong:
            self.approve(finished["audio_id"],verify=False)
        self.assertEqual(wrong.exception.reason,
            "audio_rights_verification_required")
        result=self.approve(finished["audio_id"])
        self.assertEqual(result["status"],"approved")
        same=self.start()
        self.assertTrue(same["already_imported"])
        self.assertEqual(same["audio_id"],finished["audio_id"])
        self.assertEqual(same["status"],"approved")
        self.assertEqual(len(audio.list_stems(
            self.db,"WaitingOffice","EP01")["tracks"]),1)
        self.data["stem"]="music"
        self.data["rights_ref"]="TEST-BGM-01 licensed test composition"
        another=self.start()
        self.upload(another["upload_id"])
        completed=self.finish(another["upload_id"])
        self.assertEqual(completed["revision"],1)
        self.assertEqual(len(audio.list_stems(
            self.db,"WaitingOffice","EP01")["tracks"]),2)
        with closing(core.open_db(self.db,initialize=False)) as db:
            self.assertTrue(core.verify_chain(db))

    def test_invalid_audio_or_mismatched_duration_rejected(self):
        self.data["rights_ref"]=""
        with self.assertRaises(audio.AudioError):
            self.start()
        self.data["rights_ref"]="OWN-VOICE-TEST-01"
        self.data["stem"]="../../dialogue"
        with self.assertRaises(audio.AudioError):
            self.start()
        self.data["stem"]="dialogue"
        self.content=pcm_wav(duration=2)
        self.sha=hashlib.sha256(self.content).hexdigest()
        self.data.update(file_sha256=self.sha,size_bytes=len(self.content))
        start=self.start()
        self.upload(start["upload_id"])
        with self.assertRaises(audio.AudioError) as wrong:
            self.finish(start["upload_id"])
        self.assertEqual(wrong.exception.reason,"audio_episode_duration_mismatch")

    def test_revised_stem_disables_approval_of_old_pending_version(self):
        first=self.start()
        self.upload(first["upload_id"])
        old=self.finish(first["upload_id"])
        self.data["rights_ref"]="OWN-VOICE-TEST-02 replacement license evidence"
        second=self.start()
        self.upload(second["upload_id"])
        newer=self.finish(second["upload_id"])
        self.assertEqual(newer["revision"],2)
        with self.assertRaises(audio.AudioError) as wrong:
            self.approve(old["audio_id"])
        self.assertEqual(wrong.exception.reason,"audio_revision_stale")
        self.approve(newer["audio_id"])
        tracks=audio.list_stems(self.db,"WaitingOffice","EP01")["tracks"]
        self.assertFalse(next(x for x in tracks if x["audio_id"]==
            old["audio_id"])["source_current"])

    def test_audio_private_http_range_and_owner_csrf(self):
        start=self.start()
        self.upload(start["upload_id"])
        result=self.finish(start["upload_id"])
        app=server.StudioServer(str(Path(self.db).with_name("audio-http.sqlite")),
            poller=server.Poller(probe=lambda _:{"ok":False}),
            bind=("127.0.0.1",0))
        app.production_db_path=self.db
        app.identity=fixture.MockOwner()
        thread=threading.Thread(target=app.serve_forever,daemon=True)
        thread.start()
        try:
            headers={"Host":"127.0.0.1:8900",
                "X-Forwarded-Proto":"https",
                "X-Forwarded-Host":"jipite.borealos.cn",
                "X-Director-Studio-Auth-Mode":"microsoft",
                "Origin":"https://jipite.borealos.cn",
                "Cookie":COOKIE_SID+"="+fixture.SID}
            def send(method,path,body=None,override=None):
                conn=http.client.HTTPConnection("127.0.0.1",app.server_port,
                                                timeout=8)
                opts={**headers,**(override or {})}
                if body is not None:opts["Content-Type"]="application/json"
                conn.request(method,path,headers=opts,
                    body=json.dumps(body).encode() if body is not None else None)
                response=conn.getresponse()
                code,media_type=response.status,response.getheader("Content-Type")
                content=response.read()
                conn.close()
                return code,media_type,content
            qs="?project=WaitingOffice&episode=EP01"
            self.assertEqual(send("GET","/api/v1/audio-stems"+qs,
                                  override={"Cookie":""})[0],401)
            self.assertEqual(send("GET","/api/v1/audio-stems"+qs)[0],200)
            file="/api/v1/audio-stems/file"+qs+"&audio="+result["audio_id"]
            status,mime,content=send("GET",file,override={"Range":"bytes=0-43"})
            self.assertEqual((status,mime), (206,"audio/wav"))
            self.assertEqual(content,self.content[:44])
            self.assertEqual(send("GET",file,
                override={"Range":"bytes=99999999-"})[0],416)
            payload={"csrf":fixture.CSRF,"project_id":"WaitingOffice",
                "episode_id":"EP01","audio_id":result["audio_id"],
                "decision":"approve","rights_verified":True,
                "rationale":"已完整试听并核实全部授权证明和声线同意记录。"}
            self.assertEqual(send("POST","/api/v1/audio-stems/review",
                payload,{"Cookie":""})[0],401)
            self.assertEqual(send("POST","/api/v1/audio-stems/review",
                {**payload,"csrf":"bad"})[0],403)
            self.assertEqual(send("POST","/api/v1/audio-stems/review",
                payload)[0],200)
            self.assertEqual(audio.list_stems(
                self.db,"WaitingOffice","EP01")["tracks"][0]["status"],
                "approved")
        finally:
            app.shutdown();app.server_close();thread.join(timeout=4)


if __name__=="__main__":
    unittest.main()
