from __future__ import annotations

from datetime import datetime, timezone
import unittest

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
        self._row = self._connection.next_row
        self.rowcount = self._connection.next_rowcount

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._connection.next_rows


class _Connection:
    def __init__(self) -> None:
        self.executed = []
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
            "created_at": now,
        }
        created = repo.create(
            Team(
                id="8eb8ff76-53d5-4ad3-b8b1-f63665bbf59d",
                name="River",
                short_name="CARP",
                city="Buenos Aires",
                country="Argentina",
                created_at=now,
            )
        )
        self.assertEqual(created.short_name, "CARP")
        self.assertIn("INSERT INTO teams", conn.executed[0][0])

        conn.next_rows = [conn.next_row]
        listed = repo.list_all()
        self.assertEqual(len(listed), 1)
        self.assertIn("SELECT * FROM teams", conn.executed[1][0])

        conn.next_row = {
            "id": "8eb8ff76-53d5-4ad3-b8b1-f63665bbf59d",
            "name": "Updated",
            "short_name": "UPD",
            "city": "Cordoba",
            "country": "Argentina",
            "created_at": now,
        }
        updated = repo.update(
            "8eb8ff76-53d5-4ad3-b8b1-f63665bbf59d",
            name="Updated",
            short_name="UPD",
            city="Cordoba",
            country="Argentina",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.name, "Updated")
        self.assertIn("UPDATE teams", conn.executed[2][0])

        conn.next_rowcount = 1
        deleted = repo.delete("8eb8ff76-53d5-4ad3-b8b1-f63665bbf59d")
        self.assertTrue(deleted)
        self.assertIn("DELETE FROM teams", conn.executed[3][0])


if __name__ == "__main__":
    unittest.main()
