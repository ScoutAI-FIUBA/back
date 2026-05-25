from __future__ import annotations

from dataclasses import asdict
from typing import Any, Protocol

from psycopg.rows import dict_row

from src.domain.players.entities import Player


class CursorLike(Protocol):
    def execute(self, query: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> Any: ...

    def fetchone(self) -> dict[str, Any] | tuple[Any, ...] | None: ...

    def fetchall(self) -> list[dict[str, Any]]: ...


class ConnectionLike(Protocol):
    def cursor(self, *args: Any, **kwargs: Any) -> CursorLike: ...


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
        team_id=row.get("team_id"),
    )


class PostgresPlayerRepository:
    def __init__(self, *, connection: ConnectionLike) -> None:
        self._connection = connection

    def create(self, player: Player) -> Player:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO players (
                    id, first_name, last_name, birth_date, height_cm, weight_kg, primary_position, team_id
                ) VALUES (
                    %(id)s, %(first_name)s, %(last_name)s, %(birth_date)s, %(height_cm)s, %(weight_kg)s, %(primary_position)s, %(team_id)s
                )
                RETURNING *
                """,
                asdict(player),
            )
            row = cur.fetchone()
        return _row_to_player(row) or player

    def list_all(self) -> list[Player]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM players ORDER BY last_name ASC, first_name ASC")
            rows = cur.fetchall()
        players: list[Player] = []
        for row in rows:
            player = _row_to_player(row)
            if player is not None:
                players.append(player)
        return players

    def update(self, player: Player) -> Player | None:
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
                    primary_position = %(primary_position)s
                WHERE id = %(id)s
                RETURNING *
                """,
                asdict(player),
            )
            row = cur.fetchone()
        return _row_to_player(row)

    def delete(self, player_id: str) -> bool:
        with self._connection.cursor() as cur:
            cur.execute("DELETE FROM players WHERE id = %(id)s", {"id": player_id})
            return cur.rowcount > 0

    def assign_team(self, *, player_id: str, team_id: str) -> Player | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE players
                SET team_id = %(team_id)s
                WHERE id = %(id)s
                RETURNING *
                """,
                {"id": player_id, "team_id": team_id},
            )
            row = cur.fetchone()
        return _row_to_player(row)

    def list_by_team(self, team_id: str) -> list[Player]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT *
                FROM players
                WHERE team_id = %(team_id)s
                ORDER BY last_name ASC, first_name ASC
                """,
                {"team_id": team_id},
            )
            rows = cur.fetchall()
        players: list[Player] = []
        for row in rows:
            player = _row_to_player(row)
            if player is not None:
                players.append(player)
        return players
