from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from src.domain.auth.entities import RefreshSession
from src.domain.auth.value_objects import Email, PlainPassword


class TestValueObjects(unittest.TestCase):
    def test_email_normalizes_case_and_spaces(self) -> None:
        email = Email("  USER@Example.COM ")
        self.assertEqual(email.value, "user@example.com")

    def test_email_rejects_invalid_format(self) -> None:
        with self.assertRaises(ValueError):
            Email("invalid-email")

    def test_password_policy_min_length(self) -> None:
        with self.assertRaises(ValueError):
            PlainPassword("short")
        self.assertEqual(PlainPassword("long-enough").value, "long-enough")

    def test_refresh_session_expired_and_revoked_rules(self) -> None:
        now = datetime.now(timezone.utc)
        session = RefreshSession(
            id="s1",
            user_id="u1",
            token_hash="th",
            token_jti="j1",
            family_id="f1",
            issued_at=now - timedelta(minutes=10),
            expires_at=now + timedelta(minutes=10),
        )
        self.assertTrue(session.is_active(now))
        self.assertFalse(session.is_expired(now))

        expired = RefreshSession(
            **{**session.__dict__, "expires_at": now - timedelta(seconds=1)}
        )
        self.assertTrue(expired.is_expired(now))
        self.assertFalse(expired.is_active(now))

        revoked = RefreshSession(
            **{**session.__dict__, "revoked_at": now}
        )
        self.assertTrue(revoked.is_revoked())
        self.assertFalse(revoked.is_active(now))


if __name__ == "__main__":
    unittest.main()
