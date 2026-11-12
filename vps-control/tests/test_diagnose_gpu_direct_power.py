"""Offline provider diagnostics tests: fake SDK only, never contact/start GPU."""
from __future__ import annotations
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import diagnose_gpu_direct_power as diag

CFG={"COMP_PUBLIC_KEY":"private-test-public-secret",
     "COMP_PRIVATE_KEY":"private-test-private-secret",
     "COMP_UHOST_ID":"uhost-secret-instance",
     "COMP_REGION":"cn-sh2","COMP_ZONE":"cn-sh2-01"}


class _Client:
    def __init__(self, response):
        self.calls=[]
        self.response=response
    def ucompshare(self):
        return self
    def invoke(self, action, args):
        self.calls.append((action, args))
        return self.response


class DiagnosticTests(unittest.TestCase):
    def run_diag(self, **kwargs):
        return diag.diagnose(
            config_fn=lambda:dict(CFG),uid_fn=lambda:0,
            dns_fn=lambda:None,tls_fn=lambda:None,**kwargs)

    def test_real_describe_api_never_sends_start_or_stop(self):
        c=_Client({"RetCode":0,"UHostSet":[{
            "UHostId":CFG["COMP_UHOST_ID"],"Region":"cn-sh2",
            "Zone":"cn-sh2-01","State":"Stopped"}]})
        with patch.object(diag,"create_provider_client",return_value=c):
            result=self.run_diag(instance_fn=diag.instance_check)
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"],"owner_direct")
        self.assertFalse(result["approval_required"])
        self.assertFalse(result["power_operation_executed"])
        self.assertEqual(result["provider_state"],"Stopped")
        self.assertEqual(len(c.calls),1)
        self.assertEqual(c.calls[0][0],"DescribeCompShareInstance")
        self.assertNotIn(CFG["COMP_UHOST_ID"],json.dumps(result))
        self.assertNotIn(CFG["COMP_PRIVATE_KEY"],json.dumps(result))

    def test_fail_closed_for_root_config_dns_tls_sdk(self):
        for setup, reason in (
            ({"uid_fn":lambda:1000},"root_required"),
            ({"config_fn":lambda:(_ for _ in ()).throw(ValueError(CFG["COMP_PRIVATE_KEY"]))},
                "credential_or_instance_configuration_invalid"),
            ({"dns_fn":lambda:(_ for _ in ()).throw(OSError(CFG["COMP_PRIVATE_KEY"]))},
                "provider_hostname_unreachable"),
            ({"tls_fn":lambda:(_ for _ in ()).throw(OSError(CFG["COMP_PRIVATE_KEY"]))},
                "provider_https_connection_failed"),
            ({"instance_fn":lambda c:(_ for _ in ()).throw(RuntimeError(CFG["COMP_PRIVATE_KEY"]))},
                "provider_sdk_auth_or_request_failed"),
        ):
            defaults={"config_fn":lambda:dict(CFG),"uid_fn":lambda:0,
                      "dns_fn":lambda:None,"tls_fn":lambda:None,
                      "instance_fn":lambda c:{"ok":True,"stage":"ready"}}
            defaults.update(setup)
            result=diag.diagnose(**defaults)
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"],reason)
            self.assertNotIn(CFG["COMP_PRIVATE_KEY"],str(result))

    def test_provider_rejection_or_mismatched_instance_provides_no_secrets(self):
        for response, reason in (
            ({"RetCode":1000,"Message":"secret token","UHostSet":[]},"provider_rejected"),
            ({"RetCode":0,"UHostSet":[]},"configured_instance_not_found"),
            ({"RetCode":0,"UHostSet":[{"UHostId":CFG["COMP_UHOST_ID"],
                "Region":"cn-wlcb","Zone":"cn-sh2-01","State":"Stopped"}]},
                "configured_region_zone_mismatch"),
        ):
            c=_Client(response)
            with patch.object(diag,"create_provider_client",return_value=c):
                result=self.run_diag(instance_fn=diag.instance_check)
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"],reason)
            self.assertNotIn("token",str(result))
            self.assertNotIn(CFG["COMP_UHOST_ID"],str(result))

    def test_preflight_never_claims_instance_is_started(self):
        c=_Client({"RetCode":0,"UHostSet":[{
            "UHostId":CFG["COMP_UHOST_ID"],"State":"Running"}]})
        with patch.object(diag,"create_provider_client",return_value=c):
            result=self.run_diag(instance_fn=diag.instance_check)
        self.assertEqual(result["provider_state"],"Running")
        self.assertFalse(result["power_operation_executed"])
        self.assertTrue(result["stop_requires_verified_empty_queue"])

    def test_unexpected_external_diagnostic_field_is_not_forwarded(self):
        result=self.run_diag(instance_fn=lambda c:{
            "ok":False,"stage":"provider","reason":"provider_rejected",
            "untrusted_error":CFG["COMP_PRIVATE_KEY"]})
        self.assertNotIn("untrusted_error",result)
        self.assertNotIn(CFG["COMP_PRIVATE_KEY"],str(result))


if __name__=="__main__":unittest.main()
