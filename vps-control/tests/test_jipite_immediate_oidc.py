"""Offline signature, claim and trust-boundary tests for immediate APK sync.

Synthetic RSA keys and JWTs only; tests never call Microsoft, VPS or GitHub.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
import time
import unittest

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jipite_oidc import (AuthenticationFailure, AUDIENCE, ISSUER,
                         REPOSITORY, REPOSITORY_ID, SUBJECT, WORKFLOW_REF,
                         check_claims, verify)


def b64url(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def integer_b64(value):
    return b64url(value.to_bytes((value.bit_length() + 7) // 8, "big"))


class GitHubOIDCVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = cls.key.public_key().public_numbers()
        cls.jwks = {"keys": [{
            "kid": "synthetic-ci-key", "kty": "RSA",
            "use": "sig", "alg": "RS256",
            "n": integer_b64(pub.n), "e": integer_b64(pub.e),
        }]}
        cls.now = int(time.time())

    def claims(self):
        return {
            "iss": ISSUER, "aud": AUDIENCE, "repository": REPOSITORY,
            "repository_id": REPOSITORY_ID, "ref": "refs/heads/main",
            "event_name": "workflow_run", "workflow_ref": WORKFLOW_REF,
            "sub": SUBJECT, "sha": "a" * 40, "run_id": "41838803961",
            "exp": self.now + 180, "iat": self.now - 10, "nbf": self.now - 10,
        }

    def signed(self, claims=None, alg="RS256", key=None):
        header = {"alg": alg, "kid": "synthetic-ci-key", "typ": "JWT"}
        message = b64url(json.dumps(header).encode()) + "." + b64url(
            json.dumps(self.claims() if claims is None else claims).encode())
        signing_key = key or self.key
        signature = signing_key.sign(
            message.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
        return message + "." + b64url(signature)

    def test_real_rs256_signature_verifies_using_openssl(self):
        result = verify(self.signed(), jwks=self.jwks, now=self.now)
        self.assertEqual(result["workflow_ref"], WORKFLOW_REF)

    def test_signature_tamper_rejected(self):
        token = self.signed()
        header, payload, signature = token.split(".")
        parsed = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        parsed["repository"] = "attacker/untrusted"
        forged = header + "." + b64url(json.dumps(parsed).encode()) + "." + signature
        with self.assertRaises(AuthenticationFailure):
            verify(forged, jwks=self.jwks, now=self.now)

    def test_wrong_private_key_rejected(self):
        attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with self.assertRaises(AuthenticationFailure):
            verify(self.signed(key=attacker), jwks=self.jwks, now=self.now)

    def test_reject_wrong_audience_or_workflow_or_repo(self):
        for name, value in [
            ("aud", "other-vps"), ("workflow_ref", "other-workflow"),
            ("repository", "other/repo"), ("repository_id", "1"),
            ("ref", "refs/heads/other"), ("event_name", "pull_request"),
            ("sub", "repo:untrusted/repo:ref:refs/heads/main"),
        ]:
            with self.subTest(name=name):
                claims = self.claims()
                claims[name] = value
                with self.assertRaises(AuthenticationFailure):
                    verify(self.signed(claims), jwks=self.jwks, now=self.now)

    def test_expired_and_future_tokens_rejected(self):
        for name, value in [
            ("exp", self.now - 1), ("iat", self.now - 1000),
            ("nbf", self.now + 120), ("exp", self.now + 3600),
        ]:
            with self.subTest(name=name, value=value):
                claims = self.claims()
                claims[name] = value
                with self.assertRaises(AuthenticationFailure):
                    verify(self.signed(claims), jwks=self.jwks, now=self.now)

    def test_none_algorithm_and_unknown_key_rejected(self):
        with self.assertRaises(AuthenticationFailure):
            verify(self.signed(alg="none"), jwks=self.jwks, now=self.now)
        with self.assertRaises(AuthenticationFailure):
            verify(self.signed(), jwks={"keys": []}, now=self.now)

    def test_invalid_syntax_rejected(self):
        for token in ["", "not.jwt", "a.b.c.d", " " * 8]:
            with self.subTest(token=token):
                with self.assertRaises(AuthenticationFailure):
                    verify(token, jwks=self.jwks, now=self.now)

    def test_valid_claims_do_not_require_github_network(self):
        check_claims(self.claims(), now=self.now)


if __name__ == "__main__":
    unittest.main()
