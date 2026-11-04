"""Offline functional tests for the bounded Jipite API health retry.

A fake curl is prepended to PATH, so these tests never contact the VPS.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "wait-jipite-mobile-health.sh"


class MobileStartupReadinessTests(unittest.TestCase):
    def run_case(self, fail_count: int, response: str = '{"ok":true,"mode":"device_signed"}'):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            counter = directory / "count"
            counter.write_text("0")
            fake_curl = directory / "curl"
            fake_curl.write_text(
                "#!/bin/bash\n"
                'n=$(cat "$JIPITE_TEST_COUNT")\n'
                'n=$((n+1))\n'
                'printf "%s" "$n" > "$JIPITE_TEST_COUNT"\n'
                'if (( n <= JIPITE_TEST_FAILS )); then exit 7; fi\n'
                'printf "%s\\n" "$JIPITE_TEST_BODY"\n'
            )
            fake_curl.chmod(0o755)
            fake_sleep = directory / "sleep"
            fake_sleep.write_text("#!/bin/sh\nexit 0\n")
            fake_sleep.chmod(0o755)
            env = os.environ.copy()
            env.update(
                PATH=str(directory) + os.pathsep + os.environ.get("PATH", ""),
                JIPITE_TEST_COUNT=str(counter),
                JIPITE_TEST_FAILS=str(fail_count),
                JIPITE_TEST_BODY=response,
            )
            result = subprocess.run(
                ["bash", str(SCRIPT)], env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
                check=False
            )
            return result, int(counter.read_text())

    def test_slow_bind_becomes_ready_on_third_attempt(self):
        result, attempts = self.run_case(2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(attempts, 3)
        self.assertIn("Local Android API health: OK", result.stdout)

    def test_service_never_binds_fails_after_bounded_retries(self):
        result, attempts = self.run_case(99)
        self.assertEqual(result.returncode, 5)
        self.assertEqual(attempts, 20)
        self.assertIn("failed health check after 20 attempts", result.stderr)

    def test_wrong_health_json_never_counts_as_ready(self):
        result, attempts = self.run_case(0, '{"ok":true,"mode":"wrong"}')
        self.assertEqual(result.returncode, 5)
        self.assertEqual(attempts, 1)
        self.assertIn("unexpected health response", result.stderr)


if __name__ == "__main__":
    unittest.main()
