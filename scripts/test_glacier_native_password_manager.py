"""Glacier browser password manager UX, security and cross-desktop parity.

All data is synthetic; no website accounts, real browser profiles, cookies,
tokens, passwords, device operations or running VPS are accessed by tests.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import importlib.util
import pathlib
import sys
import gc
import json
import unittest
from PySide6.QtCore import QTimer, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QListWidget, QLineEdit, QWidget

ROOT=pathlib.Path(__file__).resolve().parents[1]
WIN=ROOT/"glacier-windows"
sys.path.insert(0,str(WIN))
from glacier_password_capture38 import (
    CAPTURE_SCRIPT, validated_submission, updated_password_cards,
    GlacierPasswordCapture38)
from glacier_password_manager38 import (
    GlacierPasswordManager38, visible_password_rows38, manager_summary38)

PRIVATE={"space":"private","site":"accounts.example.org","name":"Main login",
         "username":"test@example.org","password":"synthetic-value-1",
         "code_api":""}
WORK={"space":"work","site":"accounts.example.org","name":"Work login",
      "username":"team@example.org","password":"synthetic-value-2",
      "code_api":""}

def payload(origin="https://accounts.example.org",
            username="test@example.org",password="new-password"):
    return json.dumps({"origin":origin,"username":username,"password":password})


class PasswordManagerSecurity(unittest.TestCase):
    def test_desktop_source_parity(self):
        for name in ("glacier_password_manager38.py","glacier_password_capture38.py"):
            self.assertEqual((ROOT/"glacier-windows"/name).read_bytes(),
                             (ROOT/"glacier-macos"/name).read_bytes())

    def test_isolated_trusted_capture_with_explicit_consent(self):
        for guard in ("ApplicationWorld","setRunsOnSubFrames(False)",
                      "document.addEventListener('submit'","e.isTrusted",
                      "login", "setWebChannel"):
            source=(WIN/"glacier_password_capture38.py").read_text()
            self.assertIn(guard,source)
        self.assertIn("window.top !== window",CAPTURE_SCRIPT)
        self.assertIn("location.protocol !== 'https:'",CAPTURE_SCRIPT)
        self.assertIn("pw.length !== 1",CAPTURE_SCRIPT)
        self.assertIn("bridge.submitted(data)",CAPTURE_SCRIPT)
        self.assertIn("QMessageBox.question",source)
        self.assertNotIn("console.log(",CAPTURE_SCRIPT)
        self.assertNotIn("fetch(",CAPTURE_SCRIPT)
        self.assertNotIn("localStorage.setItem(",CAPTURE_SCRIPT)

    def test_origin_binding_prevents_cross_origin_and_insecure_capture(self):
        ok=validated_submission(payload(),
                 "https://accounts.example.org/login",
                 "https://accounts.example.org/login")
        self.assertEqual(ok,{"site":"accounts.example.org",
                              "username":"test@example.org","password":"new-password"})
        for incoming,page in [
            (payload("https://evil.example.org"),"https://accounts.example.org"),
            (payload("http://accounts.example.org"),"http://accounts.example.org"),
            (payload("https://accounts.example.org:8443"),"https://accounts.example.org"),
            (payload("https://bad:pass@accounts.example.org"),"https://accounts.example.org"),
            (payload("https://accounts.example.org"),"https://other.example.org"),
            (payload("https://accounts.example.org","", "pw"),"https://accounts.example.org"),
            (payload("https://accounts.example.org","username", ""), "https://accounts.example.org"),
            ("{}", "https://accounts.example.org")
        ]:
            with self.subTest(payload=incoming[:55],page=page):
                self.assertIsNone(validated_submission(incoming,page,page))

    def test_saved_login_updates_only_same_profile_and_identity(self):
        old=[PRIVATE,WORK]
        edited=updated_password_cards(old,"private",
                {"site":"accounts.example.org","username":"test@example.org",
                 "password":"changed-value"})
        self.assertEqual(edited["accounts"][0]["password"],"changed-value")
        self.assertEqual(edited["accounts"][1],WORK)
        self.assertEqual(old[0]["password"],"synthetic-value-1")
        new=updated_password_cards(old,"private",
                {"site":"accounts.example.org","username":"new-account",
                 "password":"new-password"})
        self.assertEqual(len(new["accounts"]),3)
        self.assertTrue(any(r["username"]=="new-account" for r in new["accounts"]))
        self.assertEqual(len(visible_password_rows38(new["accounts"],"private","")),2)

    def test_manager_exposes_no_password_and_reports_actual_sync_state(self):
        s=manager_summary38([PRIVATE,WORK],
           {"token":"synthetic-token","approved":True,"auto_enabled":False})
        self.assertEqual(s["logins"],2)
        self.assertEqual(s["sites"],2)
        self.assertIn("尚未开启",s["sync"])
        subset=visible_password_rows38([PRIVATE,WORK],"private","main")
        self.assertEqual(subset,[PRIVATE])
        self.assertEqual(visible_password_rows38([PRIVATE,WORK],"work","work"),[WORK])
        self.assertEqual(visible_password_rows38([PRIVATE,WORK],"work","synthetic-value-2"),[])


class FakePasswordWindow(QWidget, GlacierPasswordManager38):
    def __init__(self):
        super().__init__()
        self._sync_state23={"token":"synthetic","approved":True,"auto_enabled":True}
        self._accounts_doc22={"accounts":[PRIVATE,WORK]}
        self._accounts_readonly22=False
    def _account_space22(self): return "private"
    def edit_account22(self,*args): return True
    def delete_account22(self,*args): return True
    def open_account_session22(self,*args): pass
    def fill_account_form22(self,*args): pass
    def _copy_account22(self,*args): pass
    def add_account22(self,*args): pass
    def show_sync23(self,*args): pass


class PasswordManagerQtUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def tearDown(self):
        for widget in list(QApplication.topLevelWidgets()):
            widget.close();widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.app.processEvents();gc.collect()

    def test_full_size_manager_has_masked_secret_search_and_real_device_status(self):
        host=FakePasswordWindow()
        observations=[]
        def inspect():
            dialog=QApplication.activeModalWidget()
            self.assertIsInstance(dialog,QDialog)
            self.assertEqual(dialog.objectName(),"GlacierPasswordManager38")
            self.assertGreaterEqual(dialog.width(),850)
            self.assertGreaterEqual(dialog.height(),580)
            rows=dialog.findChild(QListWidget,"GlacierPasswordsList38")
            self.assertIsNotNone(rows)
            self.assertEqual(rows.count(),1)  # workspace-local by default
            search=dialog.findChild(QLineEdit,"GlacierPasswordsSearch38")
            self.assertIsNotNone(search)
            texts=[x.text() for x in dialog.findChildren(QLabel)]
            self.assertIn("密码管理器",texts)
            self.assertTrue(any("自动识别" in x for x in texts))
            self.assertFalse(any("synthetic-value-1" in x for x in texts))
            self.assertFalse(any("synthetic-value-2" in x for x in texts))
            observations.append(rows.count())
            dialog.reject()
        QTimer.singleShot(0,inspect)
        host.show_password_manager38()
        self.assertEqual(observations,[1])
        host.close()


if __name__=="__main__":
    unittest.main()
