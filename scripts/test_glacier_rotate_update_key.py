"""No real GitHub writes: unit tests for one-time on-device key bootstrap."""
from __future__ import annotations
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.scripts import glacier_rotate_update_key as owner


class OwnerMigrationTests(unittest.TestCase):
    def test_gh_api_does_not_receive_unsupported_repo_flag(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0,
                                                stdout=b"{}", stderr=b"")
        with patch.object(owner.subprocess, "run", return_value=completed) as run:
            owner.gh("api", "repos/example/repo/contents/file")
            cmd = run.call_args.args[0]
            self.assertNotIn("-R", cmd)
            self.assertEqual(cmd[:2], ["gh", "api"])
            owner.gh("repo", "view", owner.REPO, "--json", "nameWithOwner")
            cmd = run.call_args.args[0]
            self.assertEqual(cmd, [
                "gh", "repo", "view", owner.REPO, "--json", "nameWithOwner"
            ])
            self.assertNotIn("-R", cmd)
            owner.gh("secret", "set", owner.SECRET, input_data=b"private-key-placeholder")
            cmd = run.call_args.args[0]
            self.assertEqual(cmd[-2:], ["-R", owner.REPO])
            self.assertNotIn("private-key-placeholder", " ".join(cmd))

    def test_locally_generated_key_is_reused_without_rotation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(owner, "HOME", root), \
                 patch.object(owner, "KEY_FILE", root / "private.hex"), \
                 patch.object(owner, "PUBLIC_FILE", root / "public.hex"):
                secret1, public1 = owner.private_key()
                secret2, public2 = owner.private_key()
                self.assertEqual((secret1, public1), (secret2, public2))
                self.assertEqual(len(secret1), 64)
                self.assertEqual(len(public1), 64)
                self.assertNotEqual(secret1, public1)

    def test_trigger_contains_only_public_fingerprint(self):
        calls = []
        def fake_gh(*args, **kw):
            calls.append((args, kw))
            return subprocess.CompletedProcess(
                args=list(args), returncode=1 if kw.get("allow_missing") else 0,
                stdout=b"", stderr=b"",
            )
        pub = "ab" * 32
        with patch.object(owner, "gh", side_effect=fake_gh):
            owner.trigger_bootstrap_builds(pub)
        puts = [args for args, _ in calls if "--method" in args]
        self.assertEqual(len(puts), 2)
        for args in puts:
            self.assertNotIn(pub, str(args))
            self.assertIn(
                hashlib.sha256(bytes.fromhex(pub)).hexdigest()[:24],
                str(args),
            )


if __name__ == "__main__":
    unittest.main()
