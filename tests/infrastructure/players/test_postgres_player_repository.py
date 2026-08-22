from __future__ import annotations

from datetime import date
import json
import unittest

from src.domain.players.entities import EMPTY_PLAYER_STATS, Player
from src.infrastructure.players.postgres_player_repository import PostgresPlayerRepository


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

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._connection.next_rows


class _Connection:
    def __init__(self) -> None:
        self.executed = []
        self.next_row = None
        self.next_rows = []

    def cursor(self, *args, **kwargs):
        return _Cursor(self)


class TestPostgresPlayerRepository(unittest.TestCase):
    def test_create_serializes_stats_with_explicit_jsonb_cast(self) -> None:
        conn = _Connection()
        repo = PostgresPlayerRepository(connection=conn)
        conn.next_row = {
            "id": "player-1",
            "first_name": "Jane",
            "last_name": "Doe",
            "birth_date": date(2000, 1, 1),
            "height_cm": 180,
            "weight_kg": 75,
            "primary_position": "G",
            "jersey_number": "7",
            "owner_user_id": "user-1",
            "team_id": "team-1",
            "stats": EMPTY_PLAYER_STATS,
        }

        repo.create(
            Player(
                id="player-1",
                first_name="Jane",
                last_name="Doe",
                birth_date=date(2000, 1, 1),
                height_cm=180,
                weight_kg=75,
                primary_position="G",
                jersey_number="7",
                owner_user_id="user-1",
                team_id="team-1",
                stats=EMPTY_PLAYER_STATS,
            )
        )

        query, params = conn.executed[0]
        self.assertIn("%(stats)s::jsonb", query)
        self.assertEqual(json.loads(params["stats"]), EMPTY_PLAYER_STATS)


if __name__ == "__main__":
    unittest.main()
