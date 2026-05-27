from __future__ import annotations

"""PostgreSQL repository adapter for team aggregates.

This module isolates SQL statements and row mapping from application use cases.
"""

from dataclasses import asdict
from typing import Any, Protocol

from psycopg.rows import dict_row

from src.domain.team.entities import Team


class CursorLike(Protocol):
    """Minimal DB-API cursor surface required by this adapter."""

    def execute(self, query: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> Any: ...

    def fetchone(self) -> dict[str, Any] | tuple[Any, ...] | None: ...

    def fetchall(self) -> list[dict[str, Any]]: ...


class ConnectionLike(Protocol):
    """Connection surface needed to open repository cursors."""

    def cursor(self, *args: Any, **kwargs: Any) -> CursorLike: ...


def _row_to_team(row: dict[str, Any] | None) -> Team | None:
    """Converts a raw teams row to a domain Team entity."""

    if row is None:
        return None
    return Team(
        id=row["id"],
        name=row["name"],
        short_name=row["short_name"],
        city=row["city"],
        country=row["country"],
        created_at=row["created_at"],
    )


class PostgresTeamRepository:
    """Team persistence adapter with explicit CRUD/exists guarantees."""

    def __init__(self, *, connection: ConnectionLike) -> None:
        self._connection = connection

    def create(self, team: Team) -> Team:
        """Inserts one team row and returns the stored aggregate state."""

        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO teams (id, name, short_name, city, country, created_at)
                VALUES (%(id)s, %(name)s, %(short_name)s, %(city)s, %(country)s, %(created_at)s)
                RETURNING *
                """,
                asdict(team),
            )
            row = cur.fetchone()
        return _row_to_team(row) or team

    def list_all(self) -> list[Team]:
        """Returns teams ordered by ``created_at DESC`` for deterministic results."""

        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM teams ORDER BY created_at DESC")
            rows = cur.fetchall()
        teams: list[Team] = []
        for row in rows:
            team = _row_to_team(row)
            if team is not None:
                teams.append(team)
        return teams

    def update(self, team_id: str, *, name: str, short_name: str, city: str, country: str) -> Team | None:
        """Updates team fields and returns ``None`` when id does not exist."""

        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE teams
                SET name = %(name)s,
                    short_name = %(short_name)s,
                    city = %(city)s,
                    country = %(country)s
                WHERE id = %(id)s
                RETURNING *
                """,
                {
                    "id": team_id,
                    "name": name,
                    "short_name": short_name,
                    "city": city,
                    "country": country,
                },
            )
            row = cur.fetchone()
        return _row_to_team(row)

    def delete(self, team_id: str) -> bool:
        """Permanently removes one team row.

        Returns ``True`` only when a row was actually deleted.
        """

        with self._connection.cursor() as cur:
            cur.execute("DELETE FROM teams WHERE id = %(id)s", {"id": team_id})
            return cur.rowcount > 0

    def exists(self, team_id: str) -> bool:
        """Existence probe used by cross-aggregate assignment workflows."""

        with self._connection.cursor() as cur:
            cur.execute("SELECT 1 FROM teams WHERE id = %(id)s", {"id": team_id})
            return cur.fetchone() is not None
