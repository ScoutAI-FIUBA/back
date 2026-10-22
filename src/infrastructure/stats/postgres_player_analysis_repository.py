from __future__ import annotations

import json
from typing import Any

from psycopg.rows import dict_row

from src.application.stats.player_analysis import (
    NOT_LATEST,
    OK,
    SIDE_CHANGED,
    PlayerAnalysisRepositoryPort,
    ReplaceResult,
)
from src.domain.players.entities import build_empty_player_stats
from src.domain.stats.player_analysis import (
    CALC_VERSION,
    PlayerGameRow,
    PlayerShotRow,
    stats_patch,
    without_nul,
)

# Only videos that still exist count: a deleted video is soft-deleted, so its rows stay
# until the job goes, and every read has to ignore them. (Hard deletes of jobs and videos
# are not exposed by the API; if they ever are, the rows go with them by cascade and the
# affected players' `players.stats` must be refreshed by whoever deletes.)
_LIVE_VIDEO = "JOIN videos v ON v.id = {alias}.video_id AND v.deleted_at IS NULL"

_INSERT_GAME = """
    INSERT INTO player_analysis_games (
        player_id, job_id, video_id, owner_user_id, jersey_number,
        seconds_on_screen, distance_m, points,
        field_goals_made, field_goals_attempted,
        two_point_made, two_point_attempted,
        three_point_made, three_point_attempted, unresolved_attempts, calc_version
    ) VALUES (
        %(player_id)s::uuid, %(job_id)s::uuid, %(video_id)s::uuid, %(owner)s, %(jersey)s,
        %(seconds)s, %(distance)s, %(points)s,
        %(fgm)s, %(fga)s, %(twom)s, %(twoa)s, %(threem)s, %(threea)s, %(unresolved)s, %(calc)s
    )
"""

_INSERT_SHOT = """
    INSERT INTO player_analysis_shots (
        player_id, job_id, video_id, owner_user_id, shot_id, outcome, shot_value, zone, shot_type,
        distance_m, court_x_m, court_y_m, timestamp_seconds, attribution, needs_review,
        outcome_source, outcome_confidence, release_timestamp_seconds, resolved_timestamp_seconds,
        shooter_candidates, calc_version
    ) VALUES (
        %(player_id)s::uuid, %(job_id)s::uuid, %(video_id)s::uuid, %(owner)s, %(shot_id)s,
        %(outcome)s, %(shot_value)s, %(zone)s, %(shot_type)s, %(distance)s, %(x)s, %(y)s,
        %(ts)s, %(attribution)s, %(review)s,
        %(source)s, %(confidence)s, %(release)s, %(resolved)s, %(candidates)s::jsonb, %(calc)s
    )
"""


def _pct(made: int, attempted: int) -> float | None:
    """A fraction (0.667), like every other stats endpoint; None when nobody shot."""

    return round(made / attempted, 3) if attempted else None


def _candidates_json(candidates: list | None) -> str | None:
    if candidates is None:
        return None
    try:
        return json.dumps(without_nul(candidates), allow_nan=False)
    except ValueError:  # a NaN or infinity inside: JSONB cannot hold it, and it is only context
        return None


def _game_params(game: PlayerGameRow) -> dict:
    return {
        "player_id": game.player_id, "job_id": game.job_id, "video_id": game.video_id,
        "owner": game.owner_user_id, "jersey": without_nul(game.jersey_number),
        "seconds": game.seconds_on_screen, "distance": game.distance_m, "points": game.points,
        "fgm": game.field_goals_made, "fga": game.field_goals_attempted,
        "twom": game.two_point_made, "twoa": game.two_point_attempted,
        "threem": game.three_point_made, "threea": game.three_point_attempted,
        "unresolved": game.unresolved_attempts, "calc": CALC_VERSION,
    }


def _shot_params(shot: PlayerShotRow) -> dict:
    return {
        "player_id": shot.player_id, "job_id": shot.job_id, "video_id": shot.video_id,
        "owner": shot.owner_user_id, "shot_id": shot.shot_id, "outcome": shot.outcome,
        "shot_value": shot.shot_value, "zone": without_nul(shot.zone), "shot_type": without_nul(shot.shot_type),
        "distance": shot.distance_m, "x": shot.court_x_m, "y": shot.court_y_m,
        "ts": shot.timestamp_seconds, "attribution": without_nul(shot.attribution),
        "review": shot.needs_review, "source": without_nul(shot.outcome_source),
        "confidence": without_nul(shot.outcome_confidence), "release": shot.release_timestamp_seconds,
        "resolved": shot.resolved_timestamp_seconds, "candidates": _candidates_json(shot.shooter_candidates),
        "calc": CALC_VERSION,
    }


class PostgresPlayerAnalysisRepository(PlayerAnalysisRepositoryPort):
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def replace_video(
        self,
        *,
        video_id: str,
        job_id: str,
        expected_side: int | None,
        games: list[PlayerGameRow],
        shots: list[PlayerShotRow],
    ) -> ReplaceResult:
        with self._connection.transaction():
            with self._connection.cursor(row_factory=dict_row) as cur:
                # One writer per video at a time. Everything below is decided inside this lock,
                # so a slow sync of an older job cannot overwrite a newer one, and two syncs of
                # the same video cannot interleave their delete and insert.
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%(v)s::text, 0))", {"v": video_id})
                cur.execute(
                    """
                    SELECT j.our_team_side,
                           j.id = (SELECT d.id FROM processing_jobs d
                                    WHERE d.video_id = j.video_id AND d.status = 'DONE'
                                    ORDER BY d.created_at DESC, d.id DESC LIMIT 1) AS is_latest
                      FROM processing_jobs j
                     WHERE j.id = %(j)s::uuid AND j.video_id = %(v)s::uuid
                    """,
                    {"j": job_id, "v": video_id},
                )
                job = cur.fetchone()
                if job is None or not job["is_latest"]:
                    return ReplaceResult(NOT_LATEST)
                if job["our_team_side"] != expected_side:
                    return ReplaceResult(SIDE_CHANGED)

                cur.execute(
                    "SELECT DISTINCT player_id FROM player_analysis_games WHERE video_id = %(v)s::uuid",
                    {"v": video_id},
                )
                wanted = {str(row["player_id"]) for row in cur.fetchall()}
                wanted.update(str(game.player_id) for game in games)
                # Players first, in a stable order, before any row that references them is
                # written: two syncs touching the same players then queue up instead of
                # deadlocking, and none of them can lose the other's totals.
                affected = self._lock_players(cur, wanted)
                games = [game for game in games if str(game.player_id) in affected]
                shots = [shot for shot in shots if str(shot.player_id) in affected]

                cur.execute("DELETE FROM player_analysis_shots WHERE video_id = %(v)s::uuid", {"v": video_id})
                cur.execute("DELETE FROM player_analysis_games WHERE video_id = %(v)s::uuid", {"v": video_id})
                if games:
                    cur.executemany(_INSERT_GAME, [_game_params(game) for game in games])
                if shots:
                    cur.executemany(_INSERT_SHOT, [_shot_params(shot) for shot in shots])
                for player_id in sorted(affected):
                    self._refresh_player_stats(cur, player_id)
        return ReplaceResult(OK, sorted(affected))

    def refresh_players_for_video(self, video_id: str) -> list[str]:
        with self._connection.transaction():
            with self._connection.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT DISTINCT player_id FROM player_analysis_games WHERE video_id = %(v)s::uuid",
                    {"v": video_id},
                )
                affected = self._lock_players(cur, {str(row["player_id"]) for row in cur.fetchall()})
                for player_id in sorted(affected):
                    self._refresh_player_stats(cur, player_id)
        return sorted(affected)

    @staticmethod
    def _lock_players(cur: Any, player_ids: set[str]) -> set[str]:
        """Lock the players that exist, sorted by id; returns their ids."""

        if not player_ids:
            return set()
        cur.execute(
            "SELECT id FROM players WHERE id = ANY(%(ids)s::uuid[]) ORDER BY id FOR UPDATE",
            {"ids": sorted(player_ids)},
        )
        return {str(row["id"]) for row in cur.fetchall()}

    def _refresh_player_stats(self, cur: Any, player_id: str) -> None:
        """Write the measured totals into `players.stats`, keeping the fields analysis cannot fill.

        The player row is locked first, so parallel syncs of different videos of the same
        player take turns and each one totals what the previous one committed.
        """

        cur.execute("SELECT stats FROM players WHERE id = %(p)s::uuid FOR UPDATE", {"p": player_id})
        row = cur.fetchone()
        if row is None:
            return
        cur.execute(
            f"""
            SELECT COUNT(*) AS games,
                   COALESCE(SUM(g.points), 0) AS points,
                   COALESCE(SUM(g.field_goals_made), 0) AS field_goals_made,
                   COALESCE(SUM(g.field_goals_attempted), 0) AS field_goals_attempted,
                   COALESCE(SUM(g.two_point_made), 0) AS two_point_made,
                   COALESCE(SUM(g.two_point_attempted), 0) AS two_point_attempted,
                   COALESCE(SUM(g.three_point_made), 0) AS three_point_made,
                   COALESCE(SUM(g.three_point_attempted), 0) AS three_point_attempted
              FROM player_analysis_games g {_LIVE_VIDEO.format(alias="g")}
             WHERE g.player_id = %(p)s::uuid
            """,
            {"p": player_id},
        )
        totals = {key: int(value) for key, value in cur.fetchone().items()}
        # A stats value that is not an object (a list, a number, a string) is corrupt: start from
        # the empty player stats instead of failing every sync of this player.
        current = row["stats"] if isinstance(row["stats"], dict) else dict(build_empty_player_stats())
        current.update(stats_patch(totals))
        cur.execute(
            "UPDATE players SET stats = %(s)s::jsonb WHERE id = %(p)s::uuid",
            {"s": json.dumps(current), "p": player_id},
        )

    def list_shots(self, *, owner_user_id: str, player_id: str) -> list[dict]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT s.id, s.job_id, s.video_id, v.title AS video_title, s.shot_id, s.outcome, s.shot_value,
                       s.zone, s.shot_type, s.distance_m, s.court_x_m, s.court_y_m, s.timestamp_seconds,
                       s.attribution, s.needs_review, s.outcome_source, s.outcome_confidence,
                       s.release_timestamp_seconds, s.resolved_timestamp_seconds
                  FROM player_analysis_shots s {_LIVE_VIDEO.format(alias="s")}
                 WHERE s.owner_user_id = %(o)s AND s.player_id = %(p)s::uuid
                 ORDER BY v.created_at, s.timestamp_seconds NULLS LAST, s.shot_id, s.id
                """,
                {"o": owner_user_id, "p": player_id},
            )
            rows = cur.fetchall()
        return [{**row, "job_id": str(row["job_id"]), "video_id": str(row["video_id"])} for row in rows]

    def totals(self, *, owner_user_id: str, player_id: str) -> dict:
        params = {"o": owner_user_id, "p": player_id}
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT g.job_id, g.video_id, v.title AS video_title, g.jersey_number, g.seconds_on_screen,
                       g.distance_m, g.points, g.field_goals_made, g.field_goals_attempted,
                       g.two_point_made, g.two_point_attempted, g.three_point_made, g.three_point_attempted,
                       g.unresolved_attempts
                  FROM player_analysis_games g {_LIVE_VIDEO.format(alias="g")}
                 WHERE g.owner_user_id = %(o)s AND g.player_id = %(p)s::uuid
                 ORDER BY v.created_at
                """,
                params,
            )
            games = cur.fetchall()
            cur.execute(
                f"""
                SELECT s.zone, s.shot_type, s.outcome, COUNT(*) AS n
                  FROM player_analysis_shots s {_LIVE_VIDEO.format(alias="s")}
                 WHERE s.owner_user_id = %(o)s AND s.player_id = %(p)s::uuid
                 GROUP BY s.zone, s.shot_type, s.outcome
                """,
                params,
            )
            shot_groups = cur.fetchall()

        def total(key: str) -> int:
            return sum(int(game[key] or 0) for game in games)

        def section(made: str, attempted: str) -> dict:
            return {"made": total(made), "attempted": total(attempted),
                    "pct": _pct(total(made), total(attempted))}

        def breakdown(field: str) -> dict:
            result: dict[str, dict] = {}
            for group in shot_groups:
                key = group[field] or "unknown"
                entry = result.setdefault(key, {"made": 0, "attempted": 0, "unresolved_attempts": 0})
                if group["outcome"] == "unresolved":
                    entry["unresolved_attempts"] += group["n"]
                else:
                    entry["attempted"] += group["n"]
                    if group["outcome"] == "made":
                        entry["made"] += group["n"]
            for entry in result.values():
                entry["pct"] = _pct(entry["made"], entry["attempted"])
            return dict(sorted(result.items()))

        seconds = [game["seconds_on_screen"] for game in games if game["seconds_on_screen"] is not None]
        distance = [game["distance_m"] for game in games if game["distance_m"] is not None]
        return {
            "games": len(games),
            "points": total("points"),
            "field_goals": section("field_goals_made", "field_goals_attempted"),
            "two_point": section("two_point_made", "two_point_attempted"),
            "three_point": section("three_point_made", "three_point_attempted"),
            "unresolved_attempts": total("unresolved_attempts"),
            "seconds_on_screen": round(sum(seconds), 1) if seconds else None,
            "distance_m": round(sum(distance), 1) if distance else None,
            "by_zone": breakdown("zone"),
            "by_shot_type": breakdown("shot_type"),
            "videos": [
                {**game, "job_id": str(game["job_id"]), "video_id": str(game["video_id"])} for game in games
            ],
            "not_measured": ["rebounds", "assists", "steals", "blocks", "turnovers", "free_throws", "minutes"],
        }
