from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from src.application.auth.errors import AuthError
from src.domain.auth.value_objects import AuthIdentity
from src.infrastructure.auth.jwt_access_token_resolver import JWTAccessTokenResolver
from src.infrastructure.auth.jwt_token_issuer import JWTTokenIssuer


class TestJWTAccessTokenResolver(unittest.TestCase):
    def test_resolve_subject_from_valid_token(self) -> None:
        issuer = JWTTokenIssuer(secret="test-secret", issuer="scoutai", audience="scoutai-client")
        resolver = JWTAccessTokenResolver(
            secret="test-secret",
            issuer="scoutai",
            audience="scoutai-client",
        )

        token = issuer.issue_access(
            identity=AuthIdentity(user_id="u1", email="u@example.com", role="user", email_verified=False),
            jti="j-1",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        self.assertEqual(resolver.resolve_subject(token), "u1")

    def test_resolve_subject_rejects_invalid_signature(self) -> None:
        resolver = JWTAccessTokenResolver(
            secret="test-secret",
            issuer="scoutai",
            audience="scoutai-client",
        )
        with self.assertRaises(AuthError):
            resolver.resolve_subject("a.b.c")


if __name__ == "__main__":
    unittest.main()
