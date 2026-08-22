from __future__ import annotations

from datetime import date
import json
import unittest

from src.domain.matches.entities import Match, MatchParticipant
from src.infrastructure.matches.postgres_repository import PostgresMatchRepository


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


class TestPostgresMatchRepository(unittest.TestCase):
    def test_create_serializes_stats_with_explicit_jsonb_cast(self) -> None:
        conn = _Connection()
        repo = PostgresMatchRepository(connection=conn)
        conn.next_row = {
            "id": "match-1",
            "owner_user_id": "user-1",
            "home_team_id": "team-home",
            "away_team_id": "team-away",
            "winner_team_id": None,
            "match_date": date(2024, 1, 1),
            "description": "Game",
            "stats": {"score": {"home": 10, "away": 9}},
        }

        repo.create(
            Match(
                id="match-1",
                owner_user_id="user-1",
                home_team_id="team-home",
                away_team_id="team-away",
                winner_team_id=None,
                match_date=date(2024, 1, 1),
                description="Game",
                stats={"score": {"home": 10, "away": 9}},
            )
        )

        query, params = conn.executed[0]
        self.assertIn("%(stats)s::jsonb", query)
        self.assertEqual(json.loads(params["stats"]), {"score": {"home": 10, "away": 9}})

    def test_replace_stats_serializes_payload_before_update(self) -> None:
        conn = _Connection()
        repo = PostgresMatchRepository(connection=conn)
        conn.next_row = {
            "id": "match-1",
            "owner_user_id": "user-1",
            "home_team_id": "team-home",
            "away_team_id": "team-away",
            "winner_team_id": "team-home",
            "match_date": date(2024, 1, 1),
            "description": "Game",
            "stats": {"winner": "home"},
        }

        repo.replace_stats(
            match_id="match-1",
            owner_user_id="user-1",
            stats={"winner": "home"},
            winner_team_id="team-home",
            participants=[
                MatchParticipant(
                    id="participant-1",
                    match_id="match-1",
                    owner_user_id="user-1",
                    player_id=None,
                    team_side="HOME",
                    display_name="Jane Doe",
                    jersey_number="7",
                )
            ],
        )

        update_query, update_params = conn.executed[0]
        self.assertIn("SET stats = %(stats)s::jsonb", update_query)
        self.assertEqual(json.loads(update_params["stats"]), {"winner": "home"})


if __name__ == "__main__":
    unittest.main()
