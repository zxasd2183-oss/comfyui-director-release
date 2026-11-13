"""Windows UE shutdown safety proof: process inventory + active jobs + auth."""
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import agent


class WorkerPowerReadinessTests(unittest.TestCase):
    def test_tasklist_parses_all_processes_and_counts_ue(self):
        ps=(
            '"System","4","Services","0","204 K"\r\n'
            '"UnrealEditor-Cmd.exe","100","Console","1","4096 K"\r\n'
            '"ShaderCompileWorker.exe","101","Console","1","1024 K"\r\n'
            '"UnrealEditor.exe","102","Console","1","9000 K"\r\n'
            '"chrome.exe","200","Console","1","1800 K"\r\n'
        )
        with patch.object(agent.subprocess,"run",
                          return_value=SimpleNamespace(returncode=0,stdout=ps)) as run:
            n=agent.count_windows_ue_processes()
        self.assertEqual(n,3)
        command=run.call_args.args[0]
        self.assertTrue(command[0].endswith("tasklist.exe"))
        self.assertEqual(command[1:],["/FO","CSV","/NH"])
        self.assertNotIn("powershell",str(command).lower())

    def test_enumeration_errors_never_authorize_stop(self):
        for stdout,status in (("",0),("unparseable process text",0),
                              ('"UnrealEditor.exe","abc","Console","1","100 K"',0),
                              ('"System","4","Services","0","204 K"',1)):
            with patch.object(agent.subprocess,"run",
                              return_value=SimpleNamespace(
                                  returncode=status,stdout=stdout)):
                with self.assertRaises(RuntimeError):
                    agent.count_windows_ue_processes()

    def test_verified_idle_requires_windows_and_full_scan(self):
        manager=SimpleNamespace(lock=threading.Lock(),active=None)
        with patch.object(agent,"JOB_MANAGER",manager), \
             patch.object(agent.platform,"system",return_value="Windows"), \
             patch.object(agent,"count_windows_ue_processes",return_value=0):
            result=agent.ue_power_readiness()
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified"])
        self.assertTrue(result["process_inventory_verified"])
        self.assertTrue(result["safe_to_stop"])
        self.assertEqual(result["active_job_id"],None)

    def test_active_job_and_stray_editor_both_block(self):
        manager=SimpleNamespace(lock=threading.Lock(),active="a"*32)
        with patch.object(agent,"JOB_MANAGER",manager), \
             patch.object(agent.platform,"system",return_value="Windows"), \
             patch.object(agent,"count_windows_ue_processes",return_value=0):
            result=agent.ue_power_readiness()
        self.assertTrue(result["verified"])
        self.assertFalse(result["safe_to_stop"])
        self.assertEqual(result["active_job_id"],"a"*32)
        manager.active=None
        with patch.object(agent,"JOB_MANAGER",manager), \
             patch.object(agent.platform,"system",return_value="Windows"), \
             patch.object(agent,"count_windows_ue_processes",return_value=1):
            result=agent.ue_power_readiness()
        self.assertFalse(result["safe_to_stop"])
        self.assertEqual(result["unreal_process_count"],1)

    def test_failed_inventory_and_missing_manager_fail_closed(self):
        with patch.object(agent,"JOB_MANAGER",None), \
             patch.object(agent.platform,"system",return_value="Windows"):
            self.assertFalse(agent.ue_power_readiness()["verified"])
        manager=SimpleNamespace(lock=threading.Lock(),active=None)
        with patch.object(agent,"JOB_MANAGER",manager), \
             patch.object(agent.platform,"system",return_value="Windows"), \
             patch.object(agent,"count_windows_ue_processes",
                          side_effect=RuntimeError("unsafe")):
            result=agent.ue_power_readiness()
        self.assertFalse(result["verified"])
        self.assertFalse(result["safe_to_stop"])

    def test_power_readiness_endpoint_requires_token(self):
        server=agent.ThreadingHTTPServer(("127.0.0.1",0),agent.Handler)
        server.token="1"*64
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        url=f"http://127.0.0.1:{server.server_port}/v7/power/readiness"
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(url,timeout=3)
            self.assertEqual(error.exception.code,401)
            data={"ok":True,"verified":True,"node_id":"ue-worker-01",
                  "kind":"director_ue_windows_power_readiness_v1",
                  "process_inventory_verified":True,
                  "unreal_process_count":0,"active_job_id":None,
                  "safe_to_stop":True,"checked_at":"2026-11-12T00:00:00+00:00",
                  "platform":"Windows"}
            with patch.object(agent,"ue_power_readiness",return_value=data):
                req=urllib.request.Request(url,headers={
                    "Authorization":"Bearer "+"1"*64})
                with urllib.request.urlopen(req,timeout=3) as response:
                    self.assertEqual(response.status,200)
                    body=json.load(response)
            self.assertEqual(body["kind"],"director_ue_windows_power_readiness_v1")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)


if __name__=="__main__":
    unittest.main()
