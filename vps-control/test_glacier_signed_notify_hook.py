"""OIDC receiver hook must only queue the one preinstalled signed unit."""
import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location("glacier_signed_notify_hook",Path(__file__).with_name("glacier_signed_notify_hook.py"))
hook=importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

class NotifyHookTests(unittest.TestCase):
    def test_only_preapproved_unit_is_invoked_without_a_shell(self):
        with patch.object(subprocess,"run") as run:
            hook.queue_signed_mirror()
        run.assert_called_once_with(
            ("/usr/bin/sudo","-n","/usr/bin/systemctl",
             "start","--no-block","glacier-signed-mirror.service"),
            check=True,timeout=10,stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE
        )

    def test_receiver_only_dropin_preserves_mirror_sandbox(self):
        root = Path(__file__).parent
        override = (root / "glacier-preview-notify.service.d"
                    / "10-signed-mirror-sudo.conf").read_text()
        mirror = (root / "glacier-signed-mirror.service").read_text()
        self.assertIn("[Service]", override)
        self.assertEqual(
            [line.strip() for line in override.splitlines()
             if line.strip().startswith("NoNewPrivileges=")],
            ["NoNewPrivileges=no"],
        )
        self.assertIn("NoNewPrivileges=true", mirror)
        self.assertNotIn("NoNewPrivileges=no", mirror)

    def test_receiver_override_installer_has_narrow_guards(self):
        root = Path(__file__).parent
        script = (root / "install-glacier-preview-notify-sudo-compat.sh").read_text()
        self.assertIn('unit="glacier-preview-notify.service"', script)
        self.assertIn('== "glacierpreview"', script)
        self.assertIn('installed_sudoers="/etc/sudoers.d/glacier-signed-mirror-notify"', script)
        # /etc/sudoers.d may be inaccessible to the normal VPS operator,
        # even though the policy exists and sudo can read it.
        self.assertIn('sudo test -f "${installed_sudoers}"', script)
        self.assertNotIn('[[ -f "${installed_sudoers}" ]]', script)
        self.assertNotIn('91-glacier-signed-mirror-notify', script)
        self.assertIn('visudo -cf', script)
        self.assertIn('sudo cmp -s', script)
        self.assertIn('sudo systemctl restart "${unit}"', script)
        self.assertNotIn('sudo systemctl restart glacier-signed-mirror.service', script)
        sudoers = (root / "glacier-signed-mirror-notify.sudoers").read_text()
        rules = [line.strip() for line in sudoers.splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(rules, [
            "glacierpreview ALL=(root) NOPASSWD: /usr/bin/systemctl start --no-block glacier-signed-mirror.service"
        ])

if __name__=="__main__":
    unittest.main()
