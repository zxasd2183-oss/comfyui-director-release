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

if __name__=="__main__":
    unittest.main()
