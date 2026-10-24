from __future__ import annotations

"""PostgreSQL repository adapter for team aggregates.

This module isolates SQL statements and row mapping from application use cases.
"""

from dataclasses import asdict
from typing import Any, Protocol

from psycopg.errors import ForeignKeyViolation
from psycopg.rows import dict_row

from src.application.team.ports import (
    TEAM_DELETE_CONFLICT_KIND_GENERIC,
    TEAM_DELETE_CONFLICT_KIND_MATCH,
    TeamDeleteConflictError,
)
from src.domain.team.entities import Team


_MATCH_DELETE_CONSTRAINTS = {
    "matches_home_team_id_fkey",
    "matches_away_team_id_fkey",
    "matches_winner_team_id_fkey",
}


def _is_match_delete_conflict(exc: ForeignKeyViolation) -> bool:
    diag = getattr(exc, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    return constraint_name in _MATCH_DELETE_CONSTRAINTS


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
        owner_user_id=row["owner_user_id"],
        created_at=row["created_at"],
    )


class PostgresTeamRepository:
    def __init__(self, *, connection: ConnectionLike) -> None:
        self._connection = connection

    def create(self, team: Team) -> Team:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO teams (id, name, short_name, city, country, owner_user_id, created_at)
                VALUES (%(id)s, %(name)s, %(short_name)s, %(city)s, %(country)s, %(owner_user_id)s, %(created_at)s)
                RETURNING *
                """,
                asdict(team),
            )
            row = cur.fetchone()
        return _row_to_team(row) or team

    def list_by_owner(self, *, owner_user_id: str) -> list[Team]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM teams WHERE owner_user_id = %(owner)s ORDER BY created_at DESC",
                {"owner": owner_user_id},
            )
            rows = cur.fetchall()
        teams: list[Team] = []
        for row in rows:
            team = _row_to_team(row)
            if team is not None:
                teams.append(team)
        return teams

    def update(
        self, team_id: str, *, owner_user_id: str, name: str, short_name: str, city: str, country: str
    ) -> Team | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE teams
                SET name = %(name)s,
                    short_name = %(short_name)s,
                    city = %(city)s,
                    country = %(country)s
                WHERE id = %(id)s AND owner_user_id = %(owner)s
                RETURNING *
                """,
                {
                    "id": team_id,
                    "name": name,
                    "short_name": short_name,
                    "city": city,
                    "country": country,
                    "owner": owner_user_id,
                },
            )
            row = cur.fetchone()
        return _row_to_team(row)

    def delete(self, team_id: str, *, owner_user_id: str) -> bool:
        with self._connection.cursor() as cur:
            try:
                cur.execute(
                    "DELETE FROM teams WHERE id = %(id)s AND owner_user_id = %(owner)s",
                    {"id": team_id, "owner": owner_user_id},
                )
            except ForeignKeyViolation as exc:
                if _is_match_delete_conflict(exc):
                    raise TeamDeleteConflictError(
                        "team has persisted matches",
                        kind=TEAM_DELETE_CONFLICT_KIND_MATCH,
                    ) from exc
                raise TeamDeleteConflictError(
                    "team has related records",
                    kind=TEAM_DELETE_CONFLICT_KIND_GENERIC,
                ) from exc
            return cur.rowcount > 0

    def is_owned_by(self, *, team_id: str, owner_user_id: str) -> bool:
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM teams WHERE id = %(id)s AND owner_user_id = %(owner)s",
                {"id": team_id, "owner": owner_user_id},
            )
            return cur.fetchone() is not None

    def lock_owned(self, *, team_id: str, owner_user_id: str) -> bool:
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM teams WHERE id = %(id)s AND owner_user_id = %(owner)s FOR UPDATE",
                {"id": team_id, "owner": owner_user_id},
            )
            return cur.fetchone() is not None
