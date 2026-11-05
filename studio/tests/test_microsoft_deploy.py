"""V0.9.1 Microsoft Web deployment preflight tests (no secrets, networks or root)."""
import json
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
import urllib.error
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import setup_microsoft_sso as setup
import promote_microsoft_nginx as nginx
import studio_identity as identity


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.client=self.root/"mobile-clientid"
        self.client.write_text("12345678-1234-1234-1234-123456789abc\n",encoding="ascii")
        self.db=self.root/"requests.db"
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE mobile_device(id TEXT PRIMARY KEY,owner_sub TEXT)")
            db.execute("INSERT INTO mobile_device VALUES (?,?)",
                       ("already_paired", "owner_subject_fixed_1234"))
        self.destination=self.root/"creds"/"msweb.json"

    def test_reuses_existing_mobile_identity_without_exposing_secret(self):
        client,subject=setup.owner_binding(self.client,self.db)
        self.assertEqual(client,"12345678-1234-1234-1234-123456789abc")
        self.assertEqual(subject,"owner_subject_fixed_1234")
        # Simulate only the root-owned /etc parent on the unprivileged CI runner.
        real_stat=Path.stat
        def root_parent(path,*args,**kwargs):
            original=real_stat(path,*args,**kwargs)
            if path == self.destination.parent:
                values=list(original)
                values[4]=0
                return os.stat_result(values)
            return original
        with patch.object(setup.os,"geteuid",return_value=0), patch.object(
                setup.Path,"stat",root_parent):
            result=setup.provision(client_file=self.client,power_db=self.db,
                destination=self.destination,
                read_secret=lambda:"a-private-studio-web-credential")
        self.assertTrue(result["owner_bound_from_jipite"])
        self.assertNotIn("a-private",json.dumps(result))
        self.assertNotIn("owner_subject",json.dumps(result))
        loaded=json.loads(self.destination.read_text())
        self.assertEqual(loaded["owner_sub"],subject)
        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode),0o600)
        self.assertIsNotNone(identity._valid_config(loaded))
        with patch.object(setup.os,"geteuid",return_value=0):
            with self.assertRaisesRegex(setup.SetupError,"refusing_overwrite"):
                setup.provision(client_file=self.client,power_db=self.db,
                    destination=self.destination,read_secret=lambda:"unexpected-credential")

    def test_missing_owner_rejects_before_secret_prompt(self):
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM mobile_device")
        prompted=[]
        with patch.object(setup.os,"geteuid",return_value=0):
            with self.assertRaisesRegex(setup.SetupError,"one_pre_enrolled"):
                setup.provision(client_file=self.client,power_db=self.db,
                    destination=self.destination,read_secret=lambda:prompted.append(True))
        self.assertEqual(prompted,[])
        self.assertFalse(self.destination.exists())

    def test_credential_file_symlink_is_refused(self):
        with patch.object(setup.os,"geteuid",return_value=0):
            self.destination.parent.mkdir()
            self.destination.symlink_to(self.client)
            with self.assertRaisesRegex(setup.SetupError,"refusing_overwrite"):
                setup.provision(client_file=self.client,power_db=self.db,
                    destination=self.destination,read_secret=lambda:"private-credential")
        self.assertEqual(self.client.read_text().strip(),
                         "12345678-1234-1234-1234-123456789abc")

    def test_no_weak_secret_or_invalid_client_registration(self):
        with patch.object(setup.os,"geteuid",return_value=0):
            with self.assertRaisesRegex(setup.SetupError,"invalid_microsoft_web_secret"):
                setup.provision(client_file=self.client,power_db=self.db,
                    destination=self.destination,read_secret=lambda:"short")
        self.client.write_text("bad_app_id",encoding="ascii")
        with self.assertRaisesRegex(setup.SetupError,"client_id_invalid"):
            setup.owner_binding(self.client,self.db)



class FakeGateOpener:
    """Offline mock: Studio denies anonymous API and starts OIDC via 302."""
    def __init__(self, transient=0, response=401, login=302):
        self.transient,self.response,self.login=transient,response,login
        self.read_calls=0
        self.start_calls=0
    def open(self,request,timeout):
        url=request.full_url
        if url.endswith("/api/v1/production"):
            self.read_calls+=1
            if self.read_calls<=self.transient:
                if self.read_calls%2:
                    raise urllib.error.URLError("connection refused during restart")
                raise urllib.error.HTTPError(url,503,"Service initializing",{},None)
            if self.response==200:
                return object()
            raise urllib.error.HTTPError(url,self.response,"denied",{},None)
        if url.endswith("/auth/start"):
            self.start_calls+=1
            headers={
                "Location":(
                    "https://login.microsoftonline.com/consumers/oauth2/v2.0/"
                    "authorize?client_id=mocked"
                ) if self.login==302 else "https://attacker.invalid/bad"
            }
            raise urllib.error.HTTPError(url,self.login,"Microsoft login",headers,None)
        raise AssertionError("Unexpected URL")


class MicrosoftGateReliabilityTests(unittest.TestCase):
    def test_retries_restart_race_but_requires_401_and_302(self):
        opener=FakeGateOpener(transient=3)
        delays=[]
        nginx.probe_backend(opener=opener,attempts=6,delay=0.1,
                            sleep=lambda s:delays.append(s))
        self.assertEqual(opener.read_calls,4)
        self.assertEqual(opener.start_calls,1)
        self.assertEqual(len(delays),3)
        self.assertTrue(all(delay<=2 for delay in delays))

    def test_never_bypasses_anonymous_read_gate_even_if_backend_is_up(self):
        opener=FakeGateOpener(response=200)
        with self.assertRaisesRegex(RuntimeError,"anonymous read"):
            nginx.probe_backend(opener=opener,attempts=5,
                                sleep=lambda _:self.fail("Unsafe retry"))
        self.assertEqual(opener.read_calls,1)
        self.assertEqual(opener.start_calls,0)

    def test_odd_403_does_not_retry_or_trigger_basic_promotion(self):
        opener=FakeGateOpener(response=403)
        with self.assertRaisesRegex(RuntimeError,"deny anonymous"):
            nginx.probe_backend(opener=opener,attempts=5,
                                sleep=lambda _:self.fail("Unexpected retry"))
        self.assertEqual(opener.read_calls,1)

    def test_wrong_oidc_redirect_never_becomes_success(self):
        opener=FakeGateOpener(login=302)
        opener.login=307
        with self.assertRaisesRegex(RuntimeError,"authorization flow"):
            nginx.probe_backend(opener=opener,attempts=6,
                                sleep=lambda _:self.fail("Unsafe retry"))

    def test_studio_never_ready_exits_with_bounded_safe_error(self):
        opener=FakeGateOpener(transient=99)
        with self.assertRaisesRegex(RuntimeError,"not_ready_after_retries"):
            nginx.probe_backend(opener=opener,attempts=3,delay=0,
                                sleep=lambda _:None)
        self.assertEqual(opener.read_calls,3)
        self.assertEqual(opener.start_calls,0)

    def test_reused_microsoft_route_is_verified_but_never_mutated(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            basic=root/"basic.conf";basic.write_text("basic")
            modern=root/"modern.conf";modern.write_text("microsoft")
            snippet=root/"active.conf";snippet.write_text("microsoft")
            with patch.object(nginx,"SNIPPET",snippet), \
                 patch.object(nginx,"MS_TEMPLATE",modern), \
                 patch.object(nginx,"BASIC_TEMPLATE",basic), \
                 patch.object(nginx.os,"geteuid",return_value=0), \
                 patch.object(nginx,"probe_backend") as probe, \
                 patch.object(nginx,"run_check") as nginx_check:
                out=StringIO()
                with redirect_stdout(out):
                    nginx.promote()
            self.assertEqual(snippet.read_text(),"microsoft")
            self.assertIn("existing Microsoft Studio route retained",out.getvalue())
            probe.assert_called_once_with()
            nginx_check.assert_not_called()

    def test_install_script_reports_reused_route_without_unverified_commit(self):
        script=(Path(__file__).resolve().parents[1]/"install-microsoft-web.sh").read_text()
        self.assertIn("ROUTE_ALREADY_MODERN=1",script)
        self.assertIn("redundant restart skipped",script)
        self.assertIn("if ! python3",script)
        self.assertIn('COMMITTED=1',script)
        self.assertLess(script.index('python3 "$SRC/promote_microsoft_nginx.py"'),
                        script.index("COMMITTED=1"))
        self.assertIn("EXISTING Microsoft Nginx route retained",script)


class NginxGateTests(unittest.TestCase):
    def test_public_route_explicitly_sets_sso_and_forwards_cookies(self):
        root=Path(__file__).resolve().parents[1]
        original=(root/"nginx-jipite-studio.conf").read_text()
        new=(root/"nginx-jipite-studio-microsoft.conf").read_text()
        self.assertIn("auth_basic_user_file /etc/nginx/.director-studio-htpasswd",original)
        self.assertIn("auth_basic off",new)
        self.assertIn("X-Director-Studio-Auth-Mode microsoft",new)
        self.assertIn("proxy_set_header Cookie $http_cookie;",new)
        self.assertIn('proxy_set_header Authorization "";',new)
        self.assertIn("access_log off;",new)
        self.assertIn("proxy_pass http://127.0.0.1:8900/;",new)
        self.assertNotIn("listen ",new)
        self.assertNotIn("0.0.0.0:8900",new)

    def test_nginx_promotion_checks_unchanged_jipite_https_server(self):
        dump="""# configuration file /etc/nginx/nginx.conf:
user www-data;
server {
listen 8443 ssl; server_name jipite.borealos.cn;
include /etc/nginx/snippets/director-studio.conf;
location ^~ /mcp/ { proxy_pass http://127.0.0.1:8897; }
}
server {listen 8443 ssl; server_name director.borealos.cn;}
"""
        nginx.verify_target_vhost(dump)
        with self.assertRaisesRegex(RuntimeError,"not uniquely"):
            nginx.verify_target_vhost(dump.replace(nginx.EXPECTED_INCLUDE,""))
        with self.assertRaisesRegex(RuntimeError,"not uniquely"):
            nginx.verify_target_vhost(dump+dump)

    def test_deployment_has_fail_closed_order(self):
        script=(Path(__file__).resolve().parents[1]/"install-microsoft-web.sh").read_text()
        self.assertLess(script.index("upgrade-v09.sh"),script.index('python3 "$SRC/promote_microsoft_nginx.py"'))
        self.assertIn("LoadCredential",(
            Path(__file__).resolve().parents[1]/"director-studio-microsoft.service.conf").read_text())
        self.assertIn("systemctl is-active --quiet director-mobile-v06",script)
        self.assertIn("getpass.getpass",(
            Path(__file__).resolve().parents[1]/"setup_microsoft_sso.py").read_text())


if __name__=="__main__":
    unittest.main()
