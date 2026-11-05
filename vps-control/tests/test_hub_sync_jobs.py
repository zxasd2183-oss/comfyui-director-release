"""Non-blocking, bounded, privacy-safe ChatGPT→Studio image transfer receipts."""
import json
import threading
import time
import unittest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hub_sync_jobs import VisualSyncJobs

REF={"file_id":"opaque-test-file-id",
     "download_url":"https://oaisdmntprcentralus.blob.core.windows.net/pic/image.png?sig=VERYSECRET",
     "file_name":"Qwen.png","mime_type":"image/png"}


class TestVisualSyncJobs(unittest.TestCase):
    def test_returns_immediate_receipt_and_completion_status(self):
        entered=threading.Event()
        release=threading.Event()
        calls=[]
        def transfer(*args):
            calls.append(args[:4])
            entered.set()
            self.assertTrue(release.wait(4))
            return {"ok":True,"visual_id":"VIS_aabbcc","version":1,
                    "unchanged":True,"gpu_action":False}
        jobs=VisualSyncJobs(transfer=transfer)
        try:
            accepted=jobs.submit("WaitingOffice","EP01","character","CHAR_QWEN",REF)
            self.assertTrue(accepted["ok"])
            self.assertTrue(accepted["job_id"].startswith("SYNC_"))
            self.assertIn(accepted["status"],("queued","running"))
            self.assertTrue(entered.wait(3))
            self.assertEqual(jobs.status(accepted["job_id"])["status"],"running")
            self.assertEqual(len(calls),1)
            # No signed URL, source file ID or query token in the status JSON.
            self.assertNotIn("VERYSECRET",json.dumps(jobs.jobs))
            self.assertNotIn(REF["download_url"],json.dumps(jobs.recent("WaitingOffice","EP01")))
            release.set()
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                finished=jobs.status(accepted["job_id"])
                if finished["status"]=="succeeded":
                    break
                time.sleep(0.01)
            self.assertEqual(finished["status"],"succeeded",finished)
            self.assertEqual(finished["result"]["visual_id"],"VIS_aabbcc")
            self.assertTrue(finished["result"]["unchanged"])
        finally:
            release.set()

    def test_same_file_id_does_not_create_second_job(self):
        lock=threading.Event()
        calls=[]
        def transfer(*args):
            calls.append(1)
            lock.wait(3)
            return {"ok":True,"visual_id":"VIS_original","version":1,
                    "unchanged":False}
        jobs=VisualSyncJobs(transfer=transfer)
        try:
            first=jobs.submit("WaitingOffice","EP01","character","CHAR_QWEN",REF)
            second=jobs.submit("WaitingOffice","EP01","character","CHAR_QWEN",REF)
            self.assertEqual(second["job_id"],first["job_id"])
            self.assertTrue(second["existing_job"])
            self.assertEqual(len(calls),1)
        finally:
            lock.set()

    def test_parallel_limit_and_opaque_identifiers(self):
        event=threading.Event()
        jobs=VisualSyncJobs(transfer=lambda *a:event.wait(3),
                            max_active=1)
        try:
            first=jobs.submit("WaitingOffice","EP01","character","CHAR_QWEN",REF)
            self.assertTrue(first["ok"])
            second=jobs.submit("WaitingOffice","EP01","character","CHAR_GPT",
                               {**REF,"file_id":"other"})
            self.assertEqual(second["reason"],"studio_sync_queue_full")
            self.assertEqual(len(jobs.recent("WaitingOffice","EP01")["jobs"]),1)
        finally:
            event.set()

    def test_rejects_untrusted_files_and_does_not_start_a_worker(self):
        jobs=VisualSyncJobs(transfer=lambda *args:self.fail("unexpected worker"))
        bad={**REF,"download_url":"http://localhost/admin?sig=secret"}
        output=jobs.submit("WaitingOffice","EP01","character","CHAR_QWEN",bad)
        self.assertEqual(output["reason"],"untrusted_chatgpt_file_host")
        self.assertEqual(jobs.recent("WaitingOffice","EP01")["jobs"],[])
        self.assertEqual(jobs.status("not-a-real-job")["reason"],
                         "invalid_sync_job_id")

    def test_failed_worker_returns_reason_without_url(self):
        jobs=VisualSyncJobs(transfer=lambda *args:{
            "ok":False,"reason":"chatgpt_download_network_error",
            "private_url":REF["download_url"]})
        started=jobs.submit("WaitingOffice","EP01","character","CHAR_QWEN",REF)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            result=jobs.status(started["job_id"])
            if result["status"]=="failed":break
            time.sleep(0.01)
        self.assertEqual(result["status"],"failed")
        self.assertEqual(result["result"]["reason"],"chatgpt_download_network_error")
        self.assertNotIn("VERYSECRET",json.dumps(result))

    def test_readback_after_lost_ack_and_ttl_expiry(self):
        now=[1000]
        jobs=VisualSyncJobs(transfer=lambda *args:{
            "ok":True,"visual_id":"VIS_old","version":1,"unchanged":True},
            clock=lambda:now[0],ttl_seconds=3600)
        receipt=jobs.submit("WaitingOffice","EP01","character","CHAR_QWEN",REF)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            status=jobs.status(receipt["job_id"])
            if status["status"]=="succeeded":break
            time.sleep(0.01)
        self.assertEqual(status["status"],"succeeded")
        recent=jobs.recent("WaitingOffice","EP01")
        self.assertEqual(recent["jobs"][0]["job_id"],receipt["job_id"])
        now[0]+=3601
        self.assertEqual(jobs.status(receipt["job_id"])["reason"],
                         "sync_job_not_found")


if __name__=="__main__":
    unittest.main()
