from __future__ import annotations

from datetime import datetime, timezone
import unittest

from src.domain.auth.entities import RefreshSession, User
from src.infrastructure.auth.postgres_repositories import (
    PostgresRefreshSessionRepository,
    PostgresUserRepository,
)


class _Cursor:
    def __init__(self, connection: "_Connection") -> None:
        self._connection = connection
        self._row = None
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self._connection.executed.append((" ".join(query.split()), params))
        self._row = self._connection.next_row
        if self._connection.next_rowcounts:
            self.rowcount = self._connection.next_rowcounts.pop(0)
        else:
            self.rowcount = self._connection.next_rowcount

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self) -> None:
        self.executed = []
        self.next_row = None
        self.next_rowcount = 0
        self.next_rowcounts: list[int] | None = None

    def cursor(self, *args, **kwargs):
        return _Cursor(self)


class TestPostgresRepositories(unittest.TestCase):
    def test_user_repository_queries_by_email_and_id(self) -> None:
        conn = _Connection()
        repo = PostgresUserRepository(connection=conn)

        conn.next_row = {
            "id": "u1",
            "email_normalized": "user@example.com",
            "password_hash": "hash",
            "email_verified": False,
            "role": "user",
            "auth_provider_id": None,
            "created_at": None,
            "updated_at": None,
            "deleted_at": None,
        }
        by_email = repo.get_by_email("user@example.com")
        self.assertIsNotNone(by_email)
        self.assertEqual(by_email.email_normalized, "user@example.com")

        conn.next_row = {
            **conn.next_row,
            "id": "u2",
            "email_normalized": "x@example.com",
        }
        by_id = repo.get_by_id("u2")
        self.assertEqual(by_id.id, "u2")
        self.assertIn("email_normalized", conn.executed[0][1])
        self.assertIn("id", conn.executed[1][1])

    def test_refresh_rotate_executes_update_then_insert(self) -> None:
        conn = _Connection()
        repo = PostgresRefreshSessionRepository(connection=conn)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        new_session = RefreshSession(
            id="s2",
            user_id="u1",
            token_hash="hash-new",
            token_jti="j2",
            family_id="f1",
            issued_at=now,
            expires_at=now,
        )
        conn.next_row = {
            "id": "s2",
            "user_id": "u1",
            "token_hash": "hash-new",
            "token_jti": "j2",
            "family_id": "f1",
            "issued_at": now,
            "expires_at": now,
            "revoked_at": None,
            "replaced_by_session_id": None,
            "reuse_detected_at": None,
            "user_agent": None,
            "ip": None,
        }

        created = repo.rotate(old_session_id="s1", new_session=new_session, revoked_at=now)
        self.assertEqual(created.id, "s2")
        self.assertEqual(len(conn.executed), 2)
        self.assertIn("UPDATE auth_refresh_sessions", conn.executed[0][0])
        self.assertIn("INSERT INTO auth_refresh_sessions", conn.executed[1][0])

    def test_refresh_rotate_skips_insert_when_old_session_not_revoked(self) -> None:
        conn = _Connection()
        conn.next_rowcounts = [0]
        repo = PostgresRefreshSessionRepository(connection=conn)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        new_session = RefreshSession(
            id="s2",
            user_id="u1",
            token_hash="hash-new",
            token_jti="j2",
            family_id="f1",
            issued_at=now,
            expires_at=now,
        )

        created = repo.rotate(old_session_id="s1", new_session=new_session, revoked_at=now)
        self.assertIsNone(created)
        self.assertEqual(len(conn.executed), 1)
        self.assertIn("UPDATE auth_refresh_sessions", conn.executed[0][0])

    def test_revoke_family_returns_affected_rows(self) -> None:
        conn = _Connection()
        conn.next_rowcount = 3
        repo = PostgresRefreshSessionRepository(connection=conn)
        affected = repo.revoke_family("family-1", datetime.now(timezone.utc))
        self.assertEqual(affected, 3)
        self.assertIn("family_id", conn.executed[0][1])

    def test_soft_delete_and_hard_delete_queries(self) -> None:
        conn = _Connection()
        repo = PostgresUserRepository(connection=conn)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        conn.next_row = {
            "id": "u1",
            "email_normalized": "user@example.com",
            "password_hash": "hash",
            "email_verified": False,
            "role": "user",
            "auth_provider_id": None,
            "created_at": now,
            "updated_at": now,
            "deleted_at": now,
        }

        deleted = repo.soft_delete("u1", now)
        self.assertIsNotNone(deleted)
        assert deleted is not None
        self.assertIsNotNone(deleted.deleted_at)
        self.assertIn("UPDATE users", conn.executed[0][0])

        conn.next_rowcount = 1
        hard_deleted = repo.hard_delete("u1")
        self.assertTrue(hard_deleted)
        self.assertIn("DELETE FROM users", conn.executed[1][0])

    def test_revoke_all_by_user_id_returns_affected_rows(self) -> None:
        conn = _Connection()
        conn.next_rowcount = 2
        repo = PostgresRefreshSessionRepository(connection=conn)
        affected = repo.revoke_all_by_user_id("u1", datetime.now(timezone.utc))
        self.assertEqual(affected, 2)
        self.assertIn("user_id", conn.executed[0][1])


if __name__ == "__main__":
    unittest.main()
