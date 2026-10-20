"""Keeps what the analyses measured for each roster player, and serves it back.

`SyncPlayerAnalysisUseCase` runs when a job finishes and when the scout marks which side is
their team. It reuses the very computation behind the per-video box score, so a player's
persisted numbers always agree with what the video's own screen shows. The read use cases
then answer across all of a player's videos: aggregated totals and every shot's court
position, ready to draw as green and red dots.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Callable

from src.application.players.errors import PLAYER_NOT_FOUND, PlayerError
from src.application.players.ports import PlayerRepositoryPort
from src.domain.jobs.entities import JobStatus, ProcessingJob
from src.domain.stats.court import court_reference
from src.domain.stats.player_analysis import (
    MADE,
    MISSED,
    PlayerGameRow,
    PlayerShotRow,
    shot_outcome,
)

logger = logging.getLogger(__name__)

# (user_id, team_id, job_id) -> the per-video game stats document the UI already shows.
GameStatsReader = Callable[..., dict]


class PlayerAnalysisRepositoryPort(ABC):
    @abstractmethod
    def replace_video(
        self, *, video_id: str, games: list[PlayerGameRow], shots: list[PlayerShotRow]
    ) -> list[str]:
        """Replace everything kept for a video and refresh the affected players' totals.

        Returns the ids of every player whose totals were recomputed.
        """

    @abstractmethod
    def list_shots(self, *, owner_user_id: str, player_id: str) -> list[dict]:
        """Every kept shot of a player, oldest video first."""

    @abstractmethod
    def totals(self, *, owner_user_id: str, player_id: str) -> dict:
        """Aggregated totals, per-zone and per-shot-type tallies and the list of games."""


def _int(value) -> int:
    return int(value or 0)


class SyncPlayerAnalysisUseCase:
    """Rebuild the kept rows of one video from its latest finished analysis."""

    def __init__(
        self,
        *,
        jobs,
        game_stats: GameStatsReader,
        analysis: PlayerAnalysisRepositoryPort,
    ) -> None:
        self._jobs = jobs
        self._game_stats = game_stats
        self._analysis = analysis

    def execute(self, job_id: str) -> int:
        """Returns how many shots were kept; 0 when the job does not apply."""

        job = self._jobs.get_by_id_unscoped(job_id=job_id)
        if job is None or job.status is not JobStatus.DONE or not job.results_key:
            return 0
        if not self._is_latest_done_for_video(job):
            # An older analysis of a video that has a newer one: the newer one decides.
            return 0

        games: list[PlayerGameRow] = []
        shots: list[PlayerShotRow] = []
        if job.our_team_side is not None:
            stats = self._game_stats(
                user_id=job.requested_by_user_id, team_id=job.team_id, job_id=job.id
            )
            games, shots = self._rows(job, stats)
        # Without a team side nothing can be tied to a roster player, and the video's
        # previous rows (from an older analysis) must not linger, so replace with nothing.
        self._analysis.replace_video(video_id=job.video_id, games=games, shots=shots)
        return len(shots)

    def _is_latest_done_for_video(self, job: ProcessingJob) -> bool:
        for other in self._jobs.list_by_video(video_id=job.video_id, team_id=job.team_id):
            if other.status is JobStatus.DONE:
                return other.id == job.id  # newest first
        return False

    @staticmethod
    def _rows(job: ProcessingJob, stats: dict) -> tuple[list[PlayerGameRow], list[PlayerShotRow]]:
        owner = job.requested_by_user_id
        games: dict[str, PlayerGameRow] = {}
        for player in stats.get("players") or []:
            player_id = player.get("roster_player_id")
            if not player_id:
                continue
            games[player_id] = PlayerGameRow(
                player_id=player_id,
                job_id=job.id,
                video_id=job.video_id,
                owner_user_id=owner,
                jersey_number=player.get("jersey_number"),
                seconds_observed=player.get("seconds_observed"),
                distance_m=player.get("distance_m"),
                points=_int(player.get("points")),
                field_goals_made=_int(player.get("field_goals_made")),
                field_goals_attempted=_int(player.get("field_goals_attempted")),
                two_point_made=_int(player.get("two_point_made")),
                two_point_attempted=_int(player.get("two_point_attempted")),
                three_point_made=_int(player.get("three_point_made")),
                three_point_attempted=_int(player.get("three_point_attempted")),
                unresolved_attempts=_int(player.get("unresolved_attempts")),
            )
        shots: list[PlayerShotRow] = []
        for row in stats.get("shots") or []:
            player_id = row.get("roster_player_id")
            if not player_id or row.get("court_x_m") is None or row.get("court_y_m") is None:
                continue
            shots.append(
                PlayerShotRow(
                    player_id=player_id,
                    job_id=job.id,
                    video_id=job.video_id,
                    owner_user_id=owner,
                    shot_id=row.get("shot_id"),
                    outcome=shot_outcome(row),
                    points=_int(row.get("points")),
                    zone=row.get("zone"),
                    shot_type=row.get("shot_type"),
                    distance_m=row.get("distance_m"),
                    court_x_m=float(row["court_x_m"]),
                    court_y_m=float(row["court_y_m"]),
                    timestamp_seconds=row.get("timestamp_seconds"),
                    attribution=row.get("attribution"),
                    needs_review=row.get("needs_review"),
                )
            )
            # A shooter can appear without a game row (not in the players list): keep it consistent.
            games.setdefault(
                player_id,
                PlayerGameRow(player_id, job.id, job.video_id, owner, row.get("jersey_number"),
                              None, None, 0, 0, 0, 0, 0, 0, 0, 0),
            )
        return list(games.values()), shots


def safe_sync(sync: SyncPlayerAnalysisUseCase | None, job_id: str) -> None:
    """Run a sync without ever failing the caller.

    Used from the job callbacks: a problem while keeping the player numbers must not turn a
    finished analysis into an error, and the numbers can always be rebuilt later.
    """

    if sync is None:
        return
    try:
        sync.execute(job_id)
    except Exception:  # noqa: BLE001 - deliberately broad, see docstring
        logger.exception("Could not sync player analysis for job %s", job_id)


class _PlayerReader:
    def __init__(self, players: PlayerRepositoryPort) -> None:
        self._players = players

    def check(self, *, user_id: str, player_id: str):
        player = self._players.get_by_id(player_id=player_id, owner_user_id=user_id)
        if player is None:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")
        return player


class GetPlayerShotChartUseCase:
    """Every shot a roster player took across their analysed videos, for a court diagram."""

    def __init__(self, *, players: PlayerRepositoryPort, analysis: PlayerAnalysisRepositoryPort) -> None:
        self._player = _PlayerReader(players)
        self._analysis = analysis

    def execute(self, *, user_id: str, player_id: str) -> dict:
        self._player.check(user_id=user_id, player_id=player_id)
        rows = self._analysis.list_shots(owner_user_id=user_id, player_id=player_id)
        shots = [
            {
                "shot_id": row["shot_id"],
                "job_id": row["job_id"],
                "video_id": row["video_id"],
                "video_title": row.get("video_title"),
                "x_m": row["court_x_m"],
                "y_m": row["court_y_m"],
                "made": row["outcome"] == MADE,
                # made draws green and missed red; unresolved is neither and stays distinct.
                "result": row["outcome"] if row["outcome"] in (MADE, MISSED) else "unknown",
                "points": row["points"],
                "zone": row["zone"],
                "shot_type": row["shot_type"],
                "distance_m": row["distance_m"],
                "timestamp_seconds": row["timestamp_seconds"],
                "attribution": row["attribution"],
                "needs_review": row["needs_review"],
            }
            for row in rows
        ]
        return {
            "player_id": player_id,
            "court": court_reference(),
            "shots": shots,
            "coverage": {
                "shots_charted": len(shots),
                "made": sum(1 for s in shots if s["result"] == MADE),
                "missed": sum(1 for s in shots if s["result"] == MISSED),
                "unresolved": sum(1 for s in shots if s["result"] == "unknown"),
                "videos": len({s["video_id"] for s in shots}),
            },
        }


class GetPlayerAnalysisStatsUseCase:
    """A roster player's measured totals across all of their analysed videos."""

    def __init__(self, *, players: PlayerRepositoryPort, analysis: PlayerAnalysisRepositoryPort) -> None:
        self._player = _PlayerReader(players)
        self._analysis = analysis

    def execute(self, *, user_id: str, player_id: str) -> dict:
        self._player.check(user_id=user_id, player_id=player_id)
        return {"player_id": player_id, **self._analysis.totals(owner_user_id=user_id, player_id=player_id)}
