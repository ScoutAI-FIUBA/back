from __future__ import annotations

from dataclasses import asdict
from datetime import date
import json
import re
from typing import Any, Protocol

from psycopg.rows import dict_row

from src.domain.players.entities import Player, PlayerStats, build_empty_player_stats

_ORDER = "ORDER BY last_name ASC, first_name ASC"
_BOX_SCORE_STATS = ("points", "rebounds", "assists", "steals", "blocks", "turnovers")
_SHOOTING_STATS = {
    "field_goals": ("field_goals",),
    "two_point": ("two_point", "two_points"),
    "three_point": ("three_point", "three_points"),
    "free_throws": ("free_throws",),
}
_INT_STRING_RE = re.compile(r"^[+-]?\d+$")


class CursorLike(Protocol):
    def execute(self, query: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> Any: ...

    def fetchone(self) -> dict[str, Any] | tuple[Any, ...] | None: ...

    def fetchall(self) -> list[dict[str, Any]]: ...


class ConnectionLike(Protocol):
    def cursor(self, *args: Any, **kwargs: Any) -> CursorLike: ...


def _as_mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not _INT_STRING_RE.fullmatch(stripped):
            return 0
        try:
            return int(stripped)
        except ValueError:
            return 0
    return 0


def _canonicalize_player_stats(stats: object) -> PlayerStats:
    canonical = build_empty_player_stats()
    source = _as_mapping(stats)

    canonical["games_played"] = _as_int(source.get("games_played"))

    record = _as_mapping(source.get("record"))
    canonical["record"] = {
        "wins": _as_int(record.get("wins", source.get("wins"))),
        "losses": _as_int(record.get("losses", source.get("losses"))),
    }

    for stat_name in _BOX_SCORE_STATS:
        section = _as_mapping(source.get(stat_name))
        canonical[stat_name] = {
            "total": _as_int(section.get("total", source.get(stat_name))),
            "per_game": _as_int(section.get("per_game")),
        }

    for stat_name, aliases in _SHOOTING_STATS.items():
        section = {}
        for alias in aliases:
            if alias in source:
                section = _as_mapping(source.get(alias))
                break
        per_game = _as_mapping(section.get("per_game"))
        canonical[stat_name] = {
            "made_total": _as_int(section.get("made_total")),
            "attempted_total": _as_int(section.get("attempted_total")),
            "per_game": {
                "made": _as_int(per_game.get("made")),
                "attempted": _as_int(per_game.get("attempted")),
            },
            "percentage": _as_int(section.get("percentage")),
        }

    return canonical


def _row_to_player(row: dict[str, Any] | None) -> Player | None:
    if row is None:
        return None
    return Player(
        id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        birth_date=row["birth_date"],
        height_cm=row["height_cm"],
        weight_kg=row["weight_kg"],
        primary_position=row["primary_position"],
        jersey_number=row.get("jersey_number"),
        owner_user_id=row["owner_user_id"],
        team_id=row.get("team_id"),
        stats=_canonicalize_player_stats(row.get("stats")),
    )


def _collect(rows: list[dict[str, Any]]) -> list[Player]:
    return [player for player in (_row_to_player(row) for row in rows) if player is not None]


class PostgresPlayerRepository:
    def __init__(self, *, connection: ConnectionLike) -> None:
        self._connection = connection

    def create(self, player: Player) -> Player:
        params = asdict(player)
        params["stats"] = json.dumps(_canonicalize_player_stats(player.stats))
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO players (
                    id, first_name, last_name, birth_date, height_cm, weight_kg,
                    primary_position, jersey_number, owner_user_id, team_id, stats
                ) VALUES (
                    %(id)s, %(first_name)s, %(last_name)s, %(birth_date)s, %(height_cm)s,
                    %(weight_kg)s, %(primary_position)s, %(jersey_number)s, %(owner_user_id)s,
                    %(team_id)s, %(stats)s::jsonb
                )
                RETURNING *
                """,
                params,
            )
            row = cur.fetchone()
        return _row_to_player(row) or player

    def get_by_id(self, *, player_id: str, owner_user_id: str) -> Player | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM players WHERE id = %(id)s AND owner_user_id = %(owner)s",
                {"id": player_id, "owner": owner_user_id},
            )
            return _row_to_player(cur.fetchone())

    def list_by_owner(self, *, owner_user_id: str) -> list[Player]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT * FROM players WHERE owner_user_id = %(owner)s {_ORDER}",
                {"owner": owner_user_id},
            )
            return _collect(cur.fetchall())

    def update(
        self,
        *,
        player_id: str,
        owner_user_id: str,
        first_name: str,
        last_name: str,
        birth_date: date,
        height_cm: int,
        weight_kg: int,
        primary_position: str,
        jersey_number: str | None,
    ) -> Player | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE players
                SET
                    first_name = %(first_name)s,
                    last_name = %(last_name)s,
                    birth_date = %(birth_date)s,
                    height_cm = %(height_cm)s,
                    weight_kg = %(weight_kg)s,
                    primary_position = %(primary_position)s,
                    jersey_number = %(jersey_number)s
                WHERE id = %(id)s AND owner_user_id = %(owner)s
                RETURNING *
                """,
                {
                    "id": player_id,
                    "owner": owner_user_id,
                    "first_name": first_name,
                    "last_name": last_name,
                    "birth_date": birth_date,
                    "height_cm": height_cm,
                    "weight_kg": weight_kg,
                    "primary_position": primary_position,
                    "jersey_number": jersey_number,
                },
            )
            return _row_to_player(cur.fetchone())

    def delete(self, player_id: str, *, owner_user_id: str) -> bool:
        with self._connection.cursor() as cur:
            cur.execute(
                "DELETE FROM players WHERE id = %(id)s AND owner_user_id = %(owner)s",
                {"id": player_id, "owner": owner_user_id},
            )
            return cur.rowcount > 0

    def assign_team(self, *, player_id: str, owner_user_id: str, team_id: str) -> Player | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE players
                SET team_id = %(team_id)s
                WHERE id = %(id)s AND owner_user_id = %(owner)s
                RETURNING *
                """,
                {"id": player_id, "owner": owner_user_id, "team_id": team_id},
            )
            return _row_to_player(cur.fetchone())

    def list_by_owner_and_team(self, *, owner_user_id: str, team_id: str) -> list[Player]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT * FROM players
                WHERE owner_user_id = %(owner)s AND team_id = %(team_id)s
                {_ORDER}
                """,
                {"owner": owner_user_id, "team_id": team_id},
            )
            return _collect(cur.fetchall())
