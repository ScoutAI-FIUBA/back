from __future__ import annotations

import json
from typing import Any

from psycopg.rows import dict_row

from src.application.stats.player_analysis import PlayerAnalysisRepositoryPort
from src.domain.stats.player_analysis import PlayerGameRow, PlayerShotRow, stats_patch

# Only videos that still exist count: a deleted video is soft-deleted, so its rows stay
# until the job goes, and every read has to ignore them.
_LIVE_VIDEO = "JOIN videos v ON v.id = {alias}.video_id AND v.deleted_at IS NULL"


def _pct(made: int, attempted: int) -> float | None:
    """A fraction (0.667), like every other stats endpoint; None when nobody shot."""

    return round(made / attempted, 3) if attempted else None


class PostgresPlayerAnalysisRepository(PlayerAnalysisRepositoryPort):
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def replace_video(
        self, *, video_id: str, games: list[PlayerGameRow], shots: list[PlayerShotRow]
    ) -> list[str]:
        with self._connection.transaction():
            with self._connection.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT DISTINCT player_id FROM player_analysis_games WHERE video_id = %(v)s::uuid",
                    {"v": video_id},
                )
                affected = {str(row["player_id"]) for row in cur.fetchall()}
                cur.execute("DELETE FROM player_analysis_shots WHERE video_id = %(v)s::uuid", {"v": video_id})
                cur.execute("DELETE FROM player_analysis_games WHERE video_id = %(v)s::uuid", {"v": video_id})
                for game in games:
                    cur.execute(
                        """
                        INSERT INTO player_analysis_games (
                            player_id, job_id, video_id, owner_user_id, jersey_number,
                            seconds_observed, distance_m, points,
                            field_goals_made, field_goals_attempted,
                            two_point_made, two_point_attempted,
                            three_point_made, three_point_attempted, unresolved_attempts
                        ) VALUES (
                            %(player_id)s::uuid, %(job_id)s::uuid, %(video_id)s::uuid, %(owner)s, %(jersey)s,
                            %(seconds)s, %(distance)s, %(points)s,
                            %(fgm)s, %(fga)s, %(twom)s, %(twoa)s, %(threem)s, %(threea)s, %(unresolved)s
                        )
                        """,
                        {
                            "player_id": game.player_id, "job_id": game.job_id, "video_id": game.video_id,
                            "owner": game.owner_user_id, "jersey": game.jersey_number,
                            "seconds": game.seconds_observed, "distance": game.distance_m, "points": game.points,
                            "fgm": game.field_goals_made, "fga": game.field_goals_attempted,
                            "twom": game.two_point_made, "twoa": game.two_point_attempted,
                            "threem": game.three_point_made, "threea": game.three_point_attempted,
                            "unresolved": game.unresolved_attempts,
                        },
                    )
                    affected.add(game.player_id)
                for shot in shots:
                    cur.execute(
                        """
                        INSERT INTO player_analysis_shots (
                            player_id, job_id, video_id, owner_user_id, shot_id, outcome, points, zone, shot_type,
                            distance_m, court_x_m, court_y_m, timestamp_seconds, attribution, needs_review
                        ) VALUES (
                            %(player_id)s::uuid, %(job_id)s::uuid, %(video_id)s::uuid, %(owner)s, %(shot_id)s,
                            %(outcome)s, %(points)s, %(zone)s, %(shot_type)s, %(distance)s, %(x)s, %(y)s,
                            %(ts)s, %(attribution)s, %(review)s
                        )
                        """,
                        {
                            "player_id": shot.player_id, "job_id": shot.job_id, "video_id": shot.video_id,
                            "owner": shot.owner_user_id, "shot_id": shot.shot_id, "outcome": shot.outcome,
                            "points": shot.points, "zone": shot.zone, "shot_type": shot.shot_type,
                            "distance": shot.distance_m, "x": shot.court_x_m, "y": shot.court_y_m,
                            "ts": shot.timestamp_seconds, "attribution": shot.attribution,
                            "review": shot.needs_review,
                        },
                    )
                for player_id in sorted(affected):
                    self._refresh_player_stats(cur, player_id)
        return sorted(affected)

    def _refresh_player_stats(self, cur: Any, player_id: str) -> None:
        """Write the measured totals into `players.stats`, keeping the fields analysis cannot fill."""

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
        cur.execute("SELECT stats FROM players WHERE id = %(p)s::uuid", {"p": player_id})
        row = cur.fetchone()
        if row is None:
            return
        current = row["stats"] if isinstance(row["stats"], dict) else json.loads(row["stats"] or "{}")
        current.update(stats_patch(totals))
        cur.execute(
            "UPDATE players SET stats = %(s)s::jsonb WHERE id = %(p)s::uuid",
            {"s": json.dumps(current), "p": player_id},
        )

    def list_shots(self, *, owner_user_id: str, player_id: str) -> list[dict]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT s.job_id, s.video_id, v.title AS video_title, s.shot_id, s.outcome, s.points, s.zone,
                       s.shot_type, s.distance_m, s.court_x_m, s.court_y_m, s.timestamp_seconds,
                       s.attribution, s.needs_review
                  FROM player_analysis_shots s {_LIVE_VIDEO.format(alias="s")}
                 WHERE s.owner_user_id = %(o)s AND s.player_id = %(p)s::uuid
                 ORDER BY v.created_at, s.timestamp_seconds NULLS LAST, s.shot_id
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
                SELECT g.job_id, g.video_id, v.title AS video_title, g.jersey_number, g.seconds_observed,
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

        seconds = [game["seconds_observed"] for game in games if game["seconds_observed"] is not None]
        distance = [game["distance_m"] for game in games if game["distance_m"] is not None]
        return {
            "games": len(games),
            "points": total("points"),
            "field_goals": section("field_goals_made", "field_goals_attempted"),
            "two_point": section("two_point_made", "two_point_attempted"),
            "three_point": section("three_point_made", "three_point_attempted"),
            "unresolved_attempts": total("unresolved_attempts"),
            "seconds_observed": round(sum(seconds), 1) if seconds else None,
            "distance_m": round(sum(distance), 1) if distance else None,
            "by_zone": breakdown("zone"),
            "by_shot_type": breakdown("shot_type"),
            "videos": [
                {**game, "job_id": str(game["job_id"]), "video_id": str(game["video_id"])} for game in games
            ],
            "not_measured": ["rebounds", "assists", "steals", "blocks", "turnovers", "free_throws", "minutes"],
        }
