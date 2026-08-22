from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any, Protocol

from psycopg.rows import dict_row

from src.domain.matches.entities import Match, MatchParticipant, MatchStatsView, TeamMatchResultSummary, TeamStatsSummary

_ORDER = "ORDER BY match_date DESC, created_at DESC"


class CursorLike(Protocol):
    def execute(self, query: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> Any: ...

    def fetchone(self) -> dict[str, Any] | tuple[Any, ...] | None: ...

    def fetchall(self) -> list[dict[str, Any]]: ...


class ConnectionLike(Protocol):
    def cursor(self, *args: Any, **kwargs: Any) -> CursorLike: ...


def _row_to_match(row: dict[str, Any] | None) -> Match | None:
    if row is None:
        return None
    return Match(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        home_team_id=row["home_team_id"],
        away_team_id=row["away_team_id"],
        winner_team_id=row.get("winner_team_id"),
        match_date=row["match_date"],
        description=row.get("description"),
        stats=row.get("stats"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _row_to_participant(row: dict[str, Any]) -> MatchParticipant:
    return MatchParticipant(
        id=row["id"],
        match_id=row["match_id"],
        owner_user_id=row["owner_user_id"],
        player_id=row.get("player_id"),
        team_side=row["team_side"],
        display_name=row["display_name"],
        jersey_number=row.get("jersey_number"),
        created_at=row.get("created_at"),
    )


class PostgresMatchRepository:
    def __init__(self, *, connection: ConnectionLike) -> None:
        self._connection = connection

    def create(self, match: Match) -> Match:
        params = asdict(match)
        params["stats"] = None if match.stats is None else json.dumps(match.stats)
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO matches (
                    id, owner_user_id, home_team_id, away_team_id, winner_team_id,
                    match_date, description, stats
                ) VALUES (
                    %(id)s, %(owner_user_id)s, %(home_team_id)s, %(away_team_id)s, %(winner_team_id)s,
                    %(match_date)s, %(description)s, %(stats)s::jsonb
                )
                RETURNING *
                """,
                params,
            )
            row = cur.fetchone()
        return _row_to_match(row) or match

    def list_by_owner(self, *, owner_user_id: str, team_id: str | None = None) -> list[Match]:
        query = "SELECT * FROM matches WHERE owner_user_id = %(owner)s"
        params: dict[str, Any] = {"owner": owner_user_id}
        if team_id is not None:
            query += " AND (home_team_id = %(team_id)s OR away_team_id = %(team_id)s)"
            params["team_id"] = team_id
        query = f"{query} {_ORDER}"
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            return [match for match in (_row_to_match(row) for row in cur.fetchall()) if match is not None]

    def get_by_id(self, *, match_id: str, owner_user_id: str) -> Match | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM matches WHERE id = %(id)s AND owner_user_id = %(owner)s",
                {"id": match_id, "owner": owner_user_id},
            )
            return _row_to_match(cur.fetchone())

    def replace_stats(
        self,
        *,
        match_id: str,
        owner_user_id: str,
        stats: Any | None,
        winner_team_id: str | None,
        participants: list[MatchParticipant],
    ) -> MatchStatsView | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE matches
                SET stats = %(stats)s::jsonb,
                    winner_team_id = %(winner_team_id)s,
                    updated_at = NOW()
                WHERE id = %(id)s AND owner_user_id = %(owner)s
                RETURNING *
                """,
                {
                    "id": match_id,
                    "owner": owner_user_id,
                    "stats": None if stats is None else json.dumps(stats),
                    "winner_team_id": winner_team_id,
                },
            )
            match_row = cur.fetchone()
            match = _row_to_match(match_row)
            if match is None:
                return None
            cur.execute(
                "DELETE FROM match_participants WHERE match_id = %(match_id)s AND owner_user_id = %(owner)s",
                {"match_id": match_id, "owner": owner_user_id},
            )
            for participant in participants:
                cur.execute(
                    """
                    INSERT INTO match_participants (
                        id, match_id, owner_user_id, player_id, team_side, display_name, jersey_number
                    ) VALUES (
                        %(id)s, %(match_id)s, %(owner_user_id)s, %(player_id)s, %(team_side)s,
                        %(display_name)s, %(jersey_number)s
                    )
                    """,
                    asdict(participant),
                )
        return self.get_stats(match_id=match_id, owner_user_id=owner_user_id)

    def get_stats(self, *, match_id: str, owner_user_id: str) -> MatchStatsView | None:
        match = self.get_by_id(match_id=match_id, owner_user_id=owner_user_id)
        if match is None:
            return None
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM match_participants
                WHERE match_id = %(match_id)s AND owner_user_id = %(owner)s
                ORDER BY created_at ASC, display_name ASC
                """,
                {"match_id": match_id, "owner": owner_user_id},
            )
            participants = [_row_to_participant(row) for row in cur.fetchall()]
        return MatchStatsView(match=match, participants=participants)

    def list_player_matches(self, *, owner_user_id: str, player_id: str) -> list[Match]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT DISTINCT m.*
                FROM matches m
                INNER JOIN match_participants mp ON mp.match_id = m.id
                WHERE m.owner_user_id = %(owner)s
                  AND mp.owner_user_id = %(owner)s
                  AND mp.player_id = %(player_id)s
                {_ORDER}
                """,
                {"owner": owner_user_id, "player_id": player_id},
            )
            return [match for match in (_row_to_match(row) for row in cur.fetchall()) if match is not None]

    def get_team_stats(self, *, owner_user_id: str, team_id: str) -> TeamStatsSummary:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT *
                FROM matches
                WHERE owner_user_id = %(owner)s
                  AND (home_team_id = %(team_id)s OR away_team_id = %(team_id)s)
                {_ORDER}
                """,
                {"owner": owner_user_id, "team_id": team_id},
            )
            rows = cur.fetchall()

        results: list[TeamMatchResultSummary] = []
        wins = 0
        losses = 0
        for row in rows:
            winner_team_id = row.get("winner_team_id")
            result = "PENDING"
            if winner_team_id == team_id:
                wins += 1
                result = "WIN"
            elif winner_team_id is not None:
                losses += 1
                result = "LOSS"
            results.append(
                TeamMatchResultSummary(
                    match_id=row["id"],
                    match_date=row["match_date"],
                    home_team_id=row["home_team_id"],
                    away_team_id=row["away_team_id"],
                    winner_team_id=winner_team_id,
                    description=row.get("description"),
                    result=result,
                )
            )

        return TeamStatsSummary(
            team_id=team_id,
            matches_played=len(rows),
            wins=wins,
            losses=losses,
            results=results,
        )
