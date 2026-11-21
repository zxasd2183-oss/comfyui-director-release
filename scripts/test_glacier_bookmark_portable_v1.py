"""End-to-end Glacier bookmark envelope tests against both desktop codecs.

Encryption is deliberately independent of account vaults and any live server.
The sample carries no credentials, cookies or real user browsing data.
"""
import importlib.util
import json
import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
FIXTURE=ROOT/"glacier-android-gecko/app/src/androidTest/assets/glacier_bookmark_portable_work_v1.json"


def module(platform):
    path=ROOT/f"glacier-{platform}/glacier_bookmark_portable_v1.py"
    spec=importlib.util.spec_from_file_location("bookmark_"+platform,path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class BookmarkPortableInterop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f=json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.win=module("windows")
        cls.mac=module("macos")

    def test_python_modules_are_identical_across_windows_and_macos(self):
        self.assertEqual(
            (ROOT/"glacier-windows/glacier_bookmark_portable_v1.py").read_bytes(),
            (ROOT/"glacier-macos/glacier_bookmark_portable_v1.py").read_bytes())

    def test_both_desktops_decrypt_android_fixture_and_deterministically_reproduce(self):
        f=self.f
        for client in (self.win,self.mac):
            with self.subTest(client=client.__name__):
                rows=client.decrypt_bookmarks("work",f["envelope"],f["passphrase"])
                self.assertEqual(rows,f["bookmarks"])
                reencrypted=client.encrypt_bookmarks(
                    "work",rows,f["passphrase"],
                    salt=bytes(range(16)),nonce=bytes(range(32,44)))
                self.assertEqual(json.loads(reencrypted),json.loads(f["envelope"]))

    def test_wrong_space_passphrase_and_tampering_fail_closed(self):
        for client in (self.win,self.mac):
            f=self.f
            for space,password in (("private",f["passphrase"]),
                                   ("work","wrong-passphrase-instead-2026")):
                with self.subTest(space=space),self.assertRaises(client.BookmarkError):
                    client.decrypt_bookmarks(space,f["envelope"],password)
            mutated=json.loads(f["envelope"])
            mutated["kdf"]="pbkdf2-sha256-100k"
            with self.assertRaises(client.BookmarkError):
                client.decrypt_bookmarks("work",json.dumps(mutated),f["passphrase"])
            mutated=json.loads(f["envelope"])
            mutated["ciphertext"]=mutated["ciphertext"][:-1]+("A" if mutated["ciphertext"][-1]!="A" else "B")
            with self.assertRaises(client.BookmarkError):
                client.decrypt_bookmarks("work",json.dumps(mutated),f["passphrase"])

    def test_randomized_encryption_never_reuses_nonce(self):
        f=self.f
        for client in (self.win,self.mac):
            one=client.encrypt_bookmarks("work",f["bookmarks"],f["passphrase"])
            two=client.encrypt_bookmarks("work",f["bookmarks"],f["passphrase"])
            self.assertNotEqual(one,two)
            self.assertEqual(client.decrypt_bookmarks("work",one,f["passphrase"]),f["bookmarks"])

    def test_import_is_additive_and_preserves_old_titles_and_space(self):
        f=self.f
        for client in (self.win,self.mac):
            local=[{"profile":"work","title":"我的旧标题",
                    "url":"https://docs.example.org/guide","at":8}]
            merged=client.merge_bookmarks(local,f["bookmarks"],"work")
            self.assertEqual(len(merged),2)
            self.assertEqual(merged[0]["title"],"我的旧标题")
            self.assertEqual(merged[1]["url"],"https://work.example.org/articles/bridge?v=1")
            self.assertEqual(len(local),1)
            with self.assertRaises(client.BookmarkError):
                client.merge_bookmarks(local,
                    [{"profile":"private","url":"https://work.example.org/a",
                      "title":"Cross","at":1}],"work")

    def test_url_limits_credentials_and_capacity_cannot_leak_or_silently_drop(self):
        for client in (self.win,self.mac):
            for url in ("file:///etc/passwd","https://user:token@example.org/a",
                        "http://localhost:1234/", "https://127.0.0.1/data",
                        "javascript:alert(1)", "https://example.org/\nsecret"):
                with self.subTest(url=url),self.assertRaises(client.BookmarkError):
                    client.encrypt_bookmarks("work",
                        [{"profile":"work","title":"Invalid","url":url,"at":1}],
                        "synthetic-only-long-passphrase")
            local=[{"profile":"work","title":"Saved","url":"https://example.org/"+str(i),
                    "at":i} for i in range(160)]
            with self.assertRaises(client.BookmarkError):
                client.merge_bookmarks(local,
                    [{"profile":"work","title":"Extra",
                      "url":"https://example.org/more","at":161}],"work")


if __name__=="__main__":
    unittest.main()
