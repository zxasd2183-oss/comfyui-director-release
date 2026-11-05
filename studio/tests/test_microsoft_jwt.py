"""Real cryptographic checks for Microsoft ID tokens, offline RSA test keys."""
import hashlib
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_identity as identity

try:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    jwt = None


@unittest.skipUnless(jwt is not None,"PyJWT/cryptography not installed in local V0.9 host")
class JwtSignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.pub = cls.private.public_key()
        cls.client_id = "12345678-1234-1234-1234-123456789abc"
        cls.expected_nonce=hashlib.sha256(b"unit-test-microsoft-nonce").hexdigest()

    def make_token(self,**changes):
        now=int(time.time())
        claims={
            "iss":identity.ISSUER, "aud":self.client_id,
            "exp":now+300,"iat":now,
            "sub":"owner_subject_fixed_1234","nonce":self.expected_nonce,
            "tid":identity.PERSONAL_TID
        }
        claims.update(changes)
        return jwt.encode(claims,self.private,algorithm="RS256",
                          headers={"kid":"unit-key"})

    def jwks(self,public_key=None):
        class KeySet:
            def get_signing_key_from_jwt(self,token):
                class Value:
                    key=public_key
                return Value()
        return KeySet()

    def test_valid_signed_personal_account_token(self):
        decoded=identity.verify_signed_id_token(
            self.make_token(),self.client_id,self.jwks(self.pub))
        self.assertEqual(decoded["sub"],"owner_subject_fixed_1234")
        self.assertEqual(decoded["nonce"],self.expected_nonce)

    def test_wrong_rsa_key_rejected_even_if_claims_look_right(self):
        attacker=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        with self.assertRaises(jwt.exceptions.InvalidSignatureError):
            identity.verify_signed_id_token(
                self.make_token(),self.client_id,self.jwks(attacker.public_key()))

    def test_wrong_audience_and_issuer_rejected(self):
        with self.assertRaises(jwt.exceptions.InvalidAudienceError):
            identity.verify_signed_id_token(self.make_token(aud="some-other-app"),
                                            self.client_id,self.jwks(self.pub))
        with self.assertRaises(jwt.exceptions.InvalidIssuerError):
            identity.verify_signed_id_token(
                self.make_token(iss="https://attacker.example/v2.0"),
                self.client_id,self.jwks(self.pub))

    def test_expired_or_unsigned_tokens_rejected(self):
        with self.assertRaises(jwt.exceptions.ExpiredSignatureError):
            identity.verify_signed_id_token(
                self.make_token(exp=int(time.time())-500),
                self.client_id,self.jwks(self.pub))
        with self.assertRaises(jwt.exceptions.InvalidAlgorithmError):
            tampered=jwt.encode({
                "iss":identity.ISSUER,"aud":self.client_id,"exp":int(time.time())+300,
                "iat":int(time.time()),"sub":"owner_subject_fixed_1234",
                "tid":identity.PERSONAL_TID,"nonce":self.expected_nonce
            },key="",algorithm="none")
            identity.verify_signed_id_token(tampered,self.client_id,self.jwks(self.pub))

    def test_missing_nonce_claim_rejected(self):
        bad=jwt.decode(self.make_token(),options={"verify_signature":False})
        bad.pop("nonce")
        token=jwt.encode(bad,self.private,algorithm="RS256",headers={"kid":"unit-key"})
        with self.assertRaises(jwt.exceptions.MissingRequiredClaimError):
            identity.verify_signed_id_token(token,self.client_id,self.jwks(self.pub))


if __name__=="__main__":
    unittest.main()
