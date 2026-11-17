"""Synthetic guards: the Glacier Sync audit never reads secrets or writes data."""
import unittest
import urllib.error
from unittest.mock import patch

from scripts.glacier_sync_readonly_audit import (
    BASES, PATHS, audit, list_services, listening_ports, probe
)


class FakeOpener:
    def __init__(self, status):
        self.status = status
        self.requests = []

    def open(self, req, timeout):
        self.requests.append((req.full_url, req.get_method(),
                              dict(req.header_items()), timeout))
        if self.status >= 400:
            raise urllib.error.HTTPError(req.full_url, self.status, "expected", {}, None)
        return FakeResponse(self.status)


class FakeResponse:
    def __init__(self, code):
        self.status = code

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, *_):
        raise AssertionError("The audit must not read response bodies")


class AuditTest(unittest.TestCase):
    def test_get_only_without_credentials(self):
        opener = FakeOpener(401)
        self.assertEqual(
            probe(BASES[0] + "/v1/session", opener=opener), {"status": 401}
        )
        self.assertEqual(opener.requests[0][1], "GET")
        headers = str(opener.requests[0][2]).lower()
        self.assertNotIn("authorization", headers)
        self.assertNotIn("cookie", headers)

    def test_errors_are_redacted(self):
        class ErrorOpener:
            def open(self, *_args, **_kwargs):
                raise urllib.error.URLError("secret-sentinel-do-not-display")
        self.assertEqual(
            probe(BASES[0] + "/health", opener=ErrorOpener()),
            {"error_type": "URLError"},
        )

    def test_inventory_no_mutations(self):
        urls = []
        def fake_probe(url, *, timeout):
            urls.append(url)
            return {"status": 404}
        with patch("scripts.glacier_sync_readonly_audit.probe",
                   side_effect=fake_probe):
            report = audit(local=False)
        self.assertEqual(len(urls), len(BASES) * len(PATHS))
        self.assertFalse(report["auth_backend_verified"])
        self.assertFalse(report["invite_issued"])
        self.assertFalse(report["eight_character_server_policy_verified"])
        self.assertTrue(all(url.startswith("https://sync.borealos.cn") for url in urls))

    def test_only_specific_systemd_service_names_are_disclosed(self):
        example = (
            "glacier-sync-api.service loaded active running Glacier\n"
            "director-hub.service loaded active running Director\n"
            "glacier-mirror.service loaded active running Mirror\n"
            "rsync.service loaded inactive dead Rsync\n"
        )
        with patch("scripts.glacier_sync_readonly_audit.run_local_command",
                   return_value=example):
            self.assertEqual(list_services(), ["glacier-sync-api.service"])

    def test_only_allowed_ports_are_disclosed(self):
        example = (
            "LISTEN 0 64 127.0.0.1:8443 0.0.0.0:*\n"
            "LISTEN 0 64 127.0.0.1:8892 0.0.0.0:*\n"
            "LISTEN 0 64 [::]:443 [::]:*\n"
        )
        with patch("scripts.glacier_sync_readonly_audit.run_local_command",
                   return_value=example):
            self.assertEqual(listening_ports(), [443, 8443])


if __name__ == "__main__":
    unittest.main()
