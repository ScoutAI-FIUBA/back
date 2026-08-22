from __future__ import annotations

from datetime import date
import json
import unittest

from src.domain.players.entities import EMPTY_PLAYER_STATS, Player
from src.infrastructure.players.postgres_player_repository import PostgresPlayerRepository, _row_to_player


def _canonical_stats(**overrides):
    stats = json.loads(json.dumps(EMPTY_PLAYER_STATS))
    for key, value in overrides.items():
        stats[key] = value
    return stats


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
        canonical_stats = _canonical_stats(
            record={"wins": 5, "losses": 1},
            points={"total": 44, "per_game": 11},
        )
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
            "stats": canonical_stats,
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
                stats=canonical_stats,
            )
        )

        query, params = conn.executed[0]
        self.assertIn("%(stats)s::jsonb", query)
        self.assertEqual(json.loads(params["stats"]), canonical_stats)

    def test_row_mapping_normalizes_legacy_flat_stats(self) -> None:
        player = _row_to_player(
            {
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
                "stats": {
                    "games_played": 9,
                    "wins": 6,
                    "losses": 3,
                    "points": 120,
                    "rebounds": 33,
                    "assists": 27,
                    "steals": 10,
                    "blocks": 4,
                    "turnovers": 8,
                },
            }
        )

        self.assertIsNotNone(player)
        self.assertEqual(player.stats["games_played"], 9)
        self.assertEqual(player.stats["record"], {"wins": 6, "losses": 3})
        self.assertEqual(player.stats["points"], {"total": 120, "per_game": 0})
        self.assertEqual(player.stats["rebounds"], {"total": 33, "per_game": 0})
        self.assertNotIn("wins", player.stats)
        self.assertNotIn("losses", player.stats)

    def test_row_mapping_zero_fills_partial_nested_sections(self) -> None:
        player = _row_to_player(
            {
                "id": "player-2",
                "first_name": "Jane",
                "last_name": "Doe",
                "birth_date": date(2000, 1, 1),
                "height_cm": 180,
                "weight_kg": 75,
                "primary_position": "G",
                "jersey_number": None,
                "owner_user_id": "user-1",
                "team_id": None,
                "stats": {
                    "games_played": 4,
                    "record": {"wins": 3},
                    "points": {"total": 48},
                    "field_goals": {"made_total": 18, "per_game": {"made": 4}},
                },
            }
        )

        self.assertIsNotNone(player)
        self.assertEqual(player.stats["record"], {"wins": 3, "losses": 0})
        self.assertEqual(player.stats["points"], {"total": 48, "per_game": 0})
        self.assertEqual(
            player.stats["field_goals"],
            {
                "made_total": 18,
                "attempted_total": 0,
                "per_game": {"made": 4, "attempted": 0},
                "percentage": 0,
            },
        )
        self.assertEqual(player.stats["three_point"], EMPTY_PLAYER_STATS["three_point"])

    def test_row_mapping_uses_runtime_coercion_policy_and_canonical_keys(self) -> None:
        player = _row_to_player(
            {
                "id": "player-4",
                "first_name": "Jane",
                "last_name": "Doe",
                "birth_date": date(2000, 1, 1),
                "height_cm": 180,
                "weight_kg": 75,
                "primary_position": "G",
                "jersey_number": None,
                "owner_user_id": "user-1",
                "team_id": None,
                "stats": {
                    "games_played": True,
                    "record": {"wins": " 7 ", "losses": False},
                    "points": {"total": 12.9, "per_game": "5"},
                    "two_points": {
                        "made_total": "9",
                        "attempted_total": 14.4,
                        "per_game": {"made": True, "attempted": " 3 "},
                        "percentage": "bad-input",
                    },
                    "three_points": {
                        "made_total": "4",
                        "attempted_total": "8",
                        "per_game": {"made": "2", "attempted": "4"},
                        "percentage": True,
                    },
                },
            }
        )

        self.assertIsNotNone(player)
        self.assertEqual(player.stats["games_played"], 1)
        self.assertEqual(player.stats["record"], {"wins": 7, "losses": 0})
        self.assertEqual(player.stats["points"], {"total": 12, "per_game": 5})
        self.assertEqual(
            player.stats["two_point"],
            {
                "made_total": 9,
                "attempted_total": 14,
                "per_game": {"made": 1, "attempted": 3},
                "percentage": 0,
            },
        )
        self.assertEqual(
            player.stats["three_point"],
            {
                "made_total": 4,
                "attempted_total": 8,
                "per_game": {"made": 2, "attempted": 4},
                "percentage": 1,
            },
        )
        self.assertEqual(set(player.stats), set(EMPTY_PLAYER_STATS))
        self.assertNotIn("two_points", player.stats)
        self.assertNotIn("three_points", player.stats)

    def test_row_mapping_turns_null_stats_into_canonical_defaults(self) -> None:
        player = _row_to_player(
            {
                "id": "player-3",
                "first_name": "Jane",
                "last_name": "Doe",
                "birth_date": date(2000, 1, 1),
                "height_cm": 180,
                "weight_kg": 75,
                "primary_position": "G",
                "jersey_number": None,
                "owner_user_id": "user-1",
                "team_id": None,
                "stats": None,
            }
        )

        self.assertIsNotNone(player)
        self.assertEqual(player.stats, EMPTY_PLAYER_STATS)


if __name__ == "__main__":
    unittest.main()
