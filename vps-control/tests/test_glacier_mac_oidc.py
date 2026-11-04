"""Regression tests for isolated Glacier macOS OIDC verification.

Uses ephemeral RSA keys and local OpenSSL, never real GitHub access or bearer secrets.
"""
import base64
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import glacier_oidc as oidc

from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives import hashes


def encode(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class GlacierOIDCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        numbers=cls.private.public_key().public_numbers()
        def integer(v):
            return encode(v.to_bytes((v.bit_length()+7)//8,"big"))
        cls.jwks={"keys":[{"kty":"RSA","alg":"RS256","use":"sig","kid":"test",
                           "n":integer(numbers.n),"e":integer(numbers.e)}]}
        cls.now=1_800_000_000

    def payload(self):
        return {
            "iss":oidc.ISSUER,
            "aud":oidc.AUDIENCE,
            "repository":oidc.REPOSITORY,
            "repository_id":oidc.REPOSITORY_ID,
            "repository_owner_id":oidc.OWNER_ID,
            "ref":"refs/heads/glacier-browser-updates",
            "workflow_ref":oidc.WORKFLOW_REF,
            "event_name":"push",
            "sub":oidc.SUBJECT,
            "iat":self.now-15,
            "nbf":self.now-20,
            "exp":self.now+180,
            "sha":"a"*40,
            "run_id":"123456789",
        }

    def jwt(self,payload):
        header={"alg":"RS256","typ":"JWT","kid":"test"}
        prefix=encode(json.dumps(header,separators=(",",":")).encode())+"."+encode(
            json.dumps(payload,separators=(",",":")).encode())
        sig=self.private.sign(prefix.encode("ascii"),padding.PKCS1v15(),hashes.SHA256())
        return prefix+"."+encode(sig)

    def verify(self,payload):
        return oidc.verify(self.jwt(payload),jwks=self.jwks,now=self.now)

    def assert_rejected(self, key, value):
        payload=self.payload()
        payload[key]=value
        with self.assertRaises(oidc.AuthenticationFailure):
            self.verify(payload)

    def test_valid_push_release_identity(self):
        self.assertEqual(self.verify(self.payload())["event_name"],"push")

    def test_valid_manual_release_identity(self):
        payload=self.payload()
        payload["event_name"]="workflow_dispatch"
        self.assertEqual(self.verify(payload)["event_name"],"workflow_dispatch")

    def test_valid_explicit_main_manual_identity(self):
        payload=self.payload()
        payload["ref"]="refs/heads/main"
        payload["workflow_ref"]=oidc.MANUAL_WORKFLOW_REF
        payload["sub"]=oidc.MAIN_SUBJECT
        payload["event_name"]="workflow_dispatch"
        self.assertEqual(self.verify(payload)["ref"],"refs/heads/main")

    def test_reject_main_manual_on_push(self):
        payload=self.payload()
        payload["ref"]="refs/heads/main"
        payload["workflow_ref"]=oidc.MANUAL_WORKFLOW_REF
        payload["sub"]=oidc.MAIN_SUBJECT
        with self.assertRaises(oidc.AuthenticationFailure):
            self.verify(payload)

    def test_reject_main_manual_claim_with_release_workflow(self):
        payload=self.payload()
        payload["ref"]="refs/heads/main"
        payload["workflow_ref"]=oidc.WORKFLOW_REF
        payload["sub"]=oidc.MAIN_SUBJECT
        payload["event_name"]="workflow_dispatch"
        with self.assertRaises(oidc.AuthenticationFailure):
            self.verify(payload)

    def test_wrong_audience_denied(self):
        self.assert_rejected("aud","jipite-vps-update-sync")

    def test_wrong_jipite_workflow_denied(self):
        self.assert_rejected("workflow_ref",oidc.REPOSITORY+
                             "/.github/workflows/jipite-immediate-sync.yml@refs/heads/main")

    def test_wrong_branch_denied(self):
        self.assert_rejected("ref","refs/heads/main")

    def test_wrong_event_denied(self):
        self.assert_rejected("event_name","pull_request")

    def test_wrong_repository_id_denied(self):
        self.assert_rejected("repository_id","1")

    def test_wrong_immutable_sub_denied(self):
        self.assert_rejected("sub","repo:zxasd2183-oss/comfyui-director-release:ref:refs/heads/main")

    def test_expired_token_denied(self):
        self.assert_rejected("exp",self.now-1)

    def test_future_token_denied(self):
        self.assert_rejected("iat",self.now+100)

    def test_bad_signature_denied(self):
        token=self.jwt(self.payload())
        payload=self.payload()
        payload["event_name"]="workflow_dispatch"
        forged=token.split(".")
        forged[1]=encode(json.dumps(payload).encode())
        with self.assertRaises(oidc.AuthenticationFailure):
            oidc.verify(".".join(forged),jwks=self.jwks,now=self.now)

    def test_unknown_key_denied(self):
        with self.assertRaises(oidc.AuthenticationFailure):
            oidc.verify(self.jwt(self.payload()),jwks={"keys":[]},now=self.now)

    def test_missing_bearer_denied(self):
        with self.assertRaises(oidc.AuthenticationFailure):
            oidc.verify("",jwks=self.jwks,now=self.now)

if __name__=="__main__":
    unittest.main()
