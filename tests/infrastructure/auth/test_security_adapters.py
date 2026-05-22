from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import unittest

from src.domain.auth.value_objects import AuthIdentity
from src.infrastructure.auth.argon2_password_hasher import Argon2PasswordHasher
from src.infrastructure.auth.jwt_token_issuer import JWTTokenIssuer
from src.infrastructure.auth.opaque_refresh_token_service import OpaqueRefreshTokenService


def _b64decode(encoded: str) -> dict[str, object]:
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    raw = base64.urlsafe_b64decode((encoded + padding).encode("utf-8"))
    return json.loads(raw.decode("utf-8"))


class TestSecurityAdapters(unittest.TestCase):
    def test_password_hasher_hash_and_verify(self) -> None:
        hasher = Argon2PasswordHasher()
        hashed = hasher.hash("my-strong-password")
        self.assertNotEqual(hashed, "my-strong-password")
        self.assertTrue(hashed.startswith("$argon2"))
        self.assertTrue(hasher.verify("my-strong-password", hashed))
        self.assertFalse(hasher.verify("wrong-password", hashed))

    def test_jwt_issuer_contains_required_claims_and_15m_ttl(self) -> None:
        issuer = JWTTokenIssuer(secret="test-secret", issuer="scoutai", audience="scoutai-client")
        now = datetime.now(timezone.utc)
        token = issuer.issue_access(
            identity=AuthIdentity(user_id="u1", email="u@example.com", role="user", email_verified=False),
            jti="j-1",
            expires_at=now + timedelta(minutes=15),
        )

        parts = token.split(".")
        self.assertEqual(len(parts), 3)
        payload = _b64decode(parts[1])
        for claim in ("sub", "iss", "aud", "iat", "exp", "jti"):
            self.assertIn(claim, payload)
        self.assertEqual(payload["sub"], "u1")
        self.assertEqual(payload["iss"], "scoutai")
        self.assertEqual(payload["aud"], "scoutai-client")
        self.assertEqual(payload["jti"], "j-1")
        self.assertGreaterEqual(payload["exp"] - payload["iat"], 890)
        self.assertLessEqual(payload["exp"] - payload["iat"], 910)

    def test_opaque_refresh_service_hash_and_fingerprint(self) -> None:
        service = OpaqueRefreshTokenService(secret="refresh-secret")
        token = service.generate_plain()
        token_hash = service.hash(token)
        self.assertNotEqual(token_hash, token)
        self.assertEqual(len(service.fingerprint(token)), 16)


if __name__ == "__main__":
    unittest.main()
