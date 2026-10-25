from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from src.application.team.ports import (
    TEAM_DELETE_CONFLICT_KIND_GENERIC,
    TEAM_DELETE_CONFLICT_KIND_MATCH,
    TeamDeleteConflictError,
)
from src.domain.team.entities import Team
from src.infrastructure.team.postgres_repository import PostgresTeamRepository


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
        if self._connection.next_error is not None:
            raise self._connection.next_error
        self._row = self._connection.next_row
        self.rowcount = self._connection.next_rowcount

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._connection.next_rows


class _Connection:
    def __init__(self) -> None:
        self.executed = []
        self.next_error = None
        self.next_row = None
        self.next_rows = []
        self.next_rowcount = 0

    def cursor(self, *args, **kwargs):
        return _Cursor(self)


class TestPostgresTeamRepository(unittest.TestCase):
    def test_create_list_update_delete_queries(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        conn = _Connection()
        repo = PostgresTeamRepository(connection=conn)

        conn.next_row = {
            "id": "8eb8ff76-53d5-4ad3-b8b1-f63665bbf59d",
            "name": "River",
            "short_name": "CARP",
            "city": "Buenos Aires",
            "country": "Argentina",
            "owner_user_id": "user-1",
            "created_at": now,
            "is_own": True,
        }
        created = repo.create(
            Team(
                id="8eb8ff76-53d5-4ad3-b8b1-f63665bbf59d",
                name="River",
                short_name="CARP",
                city="Buenos Aires",
                country="Argentina",
                owner_user_id="user-1",
                created_at=now,
                is_own=True,
            )
        )
        self.assertEqual(created.short_name, "CARP")
        self.assertTrue(created.is_own)
        self.assertIn("is_own", conn.executed[0][0])
        self.assertTrue(conn.executed[0][1]["is_own"])
        self.assertIn("INSERT INTO teams", conn.executed[0][0])

        conn.next_rows = [conn.next_row]
        listed = repo.list_by_owner(owner_user_id="user-1")
        self.assertEqual(len(listed), 1)
        self.assertIn("SELECT * FROM teams", conn.executed[1][0])
        self.assertIn("ORDER BY is_own DESC, created_at DESC", conn.executed[1][0])

        conn.next_row = {
            "id": "8eb8ff76-53d5-4ad3-b8b1-f63665bbf59d",
            "name": "Updated",
            "short_name": "UPD",
            "city": "Cordoba",
            "country": "Argentina",
            "owner_user_id": "user-1",
            "created_at": now,
        }
        updated = repo.update(
            "8eb8ff76-53d5-4ad3-b8b1-f63665bbf59d",
            owner_user_id="user-1",
            name="Updated",
            short_name="UPD",
            city="Cordoba",
            country="Argentina",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.name, "Updated")
        self.assertIn("UPDATE teams", conn.executed[2][0])
        self.assertIn("is_own = COALESCE(%(is_own)s, is_own)", conn.executed[2][0])
        self.assertIsNone(conn.executed[2][1]["is_own"])

        conn.next_rowcount = 1
        deleted = repo.delete("8eb8ff76-53d5-4ad3-b8b1-f63665bbf59d", owner_user_id="user-1")
        self.assertTrue(deleted)
        self.assertIn("DELETE FROM teams", conn.executed[3][0])

        conn.next_row = {"exists": 1}
        exists = repo.is_owned_by(team_id="8eb8ff76-53d5-4ad3-b8b1-f63665bbf59d", owner_user_id="user-1")
        self.assertTrue(exists)
        self.assertIn("SELECT 1 FROM teams", conn.executed[4][0])

    def test_delete_maps_team_fk_conflicts_to_typed_delete_conflicts(self) -> None:
        class _FakeForeignKeyViolation(Exception):
            def __init__(self, constraint_name: str) -> None:
                super().__init__(constraint_name)
                self.diag = type("Diag", (), {"constraint_name": constraint_name})()

        conn = _Connection()
        repo = PostgresTeamRepository(connection=conn)

        with patch("src.infrastructure.team.postgres_repository.ForeignKeyViolation", _FakeForeignKeyViolation):
            conn.next_error = _FakeForeignKeyViolation("matches_home_team_id_fkey")
            with self.assertRaises(TeamDeleteConflictError) as match_ctx:
                repo.delete("8eb8ff76-53d5-4ad3-b8b1-f63665bbf59d", owner_user_id="user-1")
            self.assertEqual(match_ctx.exception.kind, TEAM_DELETE_CONFLICT_KIND_MATCH)

            conn.next_error = _FakeForeignKeyViolation("videos_team_id_fkey")
            with self.assertRaises(TeamDeleteConflictError) as generic_ctx:
                repo.delete("8eb8ff76-53d5-4ad3-b8b1-f63665bbf59d", owner_user_id="user-1")
            self.assertEqual(generic_ctx.exception.kind, TEAM_DELETE_CONFLICT_KIND_GENERIC)


if __name__ == "__main__":
    unittest.main()
