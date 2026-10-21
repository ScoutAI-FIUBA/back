"""Keeps what the analyses measured for each roster player, and serves it back.

`SyncPlayerAnalysisUseCase` runs when a job finishes, when the scout marks which side is
their team, and (in the background) after a roster change. It reuses the very computation
behind the per-video box score, so the persisted numbers are that box score as it was at the
moment of the last sync. They can lag behind the per-video screen: editing a player's jersey
number or team changes who a track links to immediately on the screen, but the kept rows only
follow once `ResyncTeamAnalysesUseCase` has re-run (bounded to the team's latest analyses),
and analyses older than that bound keep their old links until the side is saved again. The read
use cases then answer across all of a player's videos: aggregated totals and every shot's court
position, ready to draw as green and red dots.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from src.application.players.errors import PLAYER_NOT_FOUND, PlayerError
from src.application.players.ports import PlayerRepositoryPort
from src.domain.jobs.entities import JobStatus, ProcessingJob
from src.domain.stats.court import court_reference
from src.domain.stats.player_analysis import (
    CALC_VERSION,
    MADE,
    MISSED,
    PlayerGameRow,
    PlayerShotRow,
    shot_outcome,
)

logger = logging.getLogger(__name__)

# (user_id, team_id, job_id) -> the per-video game stats document the UI already shows.
GameStatsReader = Callable[..., dict]

# What a sync (and a replace) can report.
OK = "ok"
FAILED = "failed"
NOT_LATEST = "not_latest"
SIDE_CHANGED = "side_changed"
NO_SIDE = "no_side"
NOT_READY = "not_ready"
JOB_NOT_FOUND = "job_not_found"

# Values the table accepts for `outcome_confidence`; anything else is stored as unknown.
_CONFIDENCES = frozenset({"detected", "inferred", "timeout", "unresolved"})

# How many of a team's latest analyses a roster change re-syncs.
RESYNC_LIMIT = 20


@dataclass(frozen=True)
class ReplaceResult:
    """What `replace_video` did: `ok`, `not_latest` or `side_changed` (nothing was changed)."""

    status: str
    players: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SyncResult:
    """What a sync did: one of the status constants above, how many shots were kept and how many dropped."""

    status: str
    shots_kept: int = 0
    shots_skipped: int = 0


class PlayerAnalysisRepositoryPort(ABC):
    @abstractmethod
    def replace_video(
        self,
        *,
        video_id: str,
        job_id: str,
        expected_side: int | None,
        games: list[PlayerGameRow],
        shots: list[PlayerShotRow],
    ) -> ReplaceResult:
        """Replace everything kept for a video and refresh the affected players' totals.

        Serialised per video. Inside that lock it re-checks that `job_id` is still the latest
        DONE job of the video and that the job's team side is still `expected_side`; if not,
        nothing is changed and the status says why.
        """

    @abstractmethod
    def refresh_players_for_video(self, video_id: str) -> list[str]:
        """Recompute the totals of every player that has rows for the video (soft-deleted videos excluded)."""

    @abstractmethod
    def list_shots(self, *, owner_user_id: str, player_id: str) -> list[dict]:
        """Every kept shot of a player, oldest video first, each with its row `id`."""

    @abstractmethod
    def totals(self, *, owner_user_id: str, player_id: str) -> dict:
        """Aggregated totals, per-zone and per-shot-type tallies and the list of games."""


def _int(value) -> int:
    return int(value or 0)


def _finite(value) -> float | None:
    """The value as a float, or None when it is missing or not a finite number."""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _add(first: float | None, second: float | None) -> float | None:
    if first is None:
        return second
    return first if second is None else first + second


_SUMMED = (
    "points", "field_goals_made", "field_goals_attempted", "two_point_made", "two_point_attempted",
    "three_point_made", "three_point_attempted", "unresolved_attempts",
)


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

    def execute(self, job_id: str) -> SyncResult:
        """Returns the status (and how many shots were kept); anything but `ok` changed nothing,
        except `no_side`, which clears the video's rows."""

        job = self._jobs.get_by_id_unscoped(job_id=job_id)
        if job is None:
            return SyncResult(JOB_NOT_FOUND)
        if job.status is not JobStatus.DONE or not job.results_key:
            return SyncResult(NOT_READY)
        if not self._is_latest_done_for_video(job):
            # An older analysis of a video that has a newer one: the newer one decides.
            return SyncResult(NOT_LATEST)

        games: list[PlayerGameRow] = []
        shots: list[PlayerShotRow] = []
        skipped = 0
        side = job.our_team_side
        if side is not None:
            # The slow part (object storage reads) runs here, outside the database lock.
            stats = self._game_stats(
                user_id=job.requested_by_user_id, team_id=job.team_id, job_id=job.id
            )
            games, shots, skipped = self._rows(job, stats)
        # Without a team side nothing can be tied to a roster player, and the video's
        # previous rows (from an older analysis) must not linger, so replace with nothing.
        replaced = self._analysis.replace_video(
            video_id=job.video_id, job_id=job.id, expected_side=side, games=games, shots=shots
        )
        if replaced.status != OK:
            return SyncResult(replaced.status)
        if side is None:
            return SyncResult(NO_SIDE)
        return SyncResult(OK, shots_kept=len(shots), shots_skipped=skipped)

    def _is_latest_done_for_video(self, job: ProcessingJob) -> bool:
        for other in self._jobs.list_by_video(video_id=job.video_id, team_id=job.team_id):
            if other.status is JobStatus.DONE:
                return other.id == job.id  # newest first
        return False

    @staticmethod
    def _rows(
        job: ProcessingJob, stats: dict
    ) -> tuple[list[PlayerGameRow], list[PlayerShotRow], int]:
        """The rows to keep, plus how many shots were dropped for unusable numbers."""

        owner = job.requested_by_user_id
        # Several tracks of the video can link to the same roster player (two tracks that
        # both confirmed the same jersey): their numbers add up, they are not overwritten.
        totals: dict[str, dict] = {}
        for player in stats.get("players") or []:
            player_id = player.get("roster_player_id")
            if not player_id:
                continue
            player_id = str(player_id)  # the roster repository hands out UUID objects
            entry = totals.get(player_id)
            if entry is None:
                entry = totals[player_id] = {
                    "jersey_number": None, "seconds": None, "distance": None, **{key: 0 for key in _SUMMED}
                }
            if entry["jersey_number"] is None:
                entry["jersey_number"] = player.get("jersey_number")
            entry["seconds"] = _add(entry["seconds"], _finite(player.get("seconds_observed")))
            entry["distance"] = _add(entry["distance"], _finite(player.get("distance_m")))
            for key in _SUMMED:
                entry[key] += _int(player.get(key))
        games: dict[str, PlayerGameRow] = {
            player_id: PlayerGameRow(
                player_id=player_id,
                job_id=job.id,
                video_id=job.video_id,
                owner_user_id=owner,
                jersey_number=entry["jersey_number"],
                seconds_on_screen=entry["seconds"],
                distance_m=entry["distance"],
                **{key: entry[key] for key in _SUMMED},
            )
            for player_id, entry in totals.items()
        }

        shots: list[PlayerShotRow] = []
        seen_shot_ids: set[int] = set()
        skipped = 0
        for row in stats.get("shots") or []:
            player_id = row.get("roster_player_id")
            if not player_id:
                continue
            player_id = str(player_id)
            x, y = _finite(row.get("court_x_m")), _finite(row.get("court_y_m"))
            value, distance = _finite(row.get("points")), _finite(row.get("distance_m"))
            if row.get("court_x_m") is None or row.get("court_y_m") is None:
                continue  # never placed on the court: not a located shot, nothing to count
            if x is None or y is None or value not in (2.0, 3.0) or distance is None:
                skipped += 1
                continue
            shot_id = row.get("shot_id")
            try:
                shot_id = None if shot_id is None else int(shot_id)
            except (TypeError, ValueError):
                shot_id = None
            if shot_id is not None:
                if shot_id in seen_shot_ids:
                    shot_id = None  # the pipeline repeated an id: keep the shot, not the id
                else:
                    seen_shot_ids.add(shot_id)
            confidence = row.get("outcome_confidence")
            candidates = row.get("shooter_candidates")
            shots.append(
                PlayerShotRow(
                    player_id=player_id,
                    job_id=job.id,
                    video_id=job.video_id,
                    owner_user_id=owner,
                    shot_id=shot_id,
                    outcome=shot_outcome(row),
                    shot_value=int(value),
                    zone=row.get("zone"),
                    shot_type=row.get("shot_type"),
                    distance_m=distance,
                    court_x_m=x,
                    court_y_m=y,
                    timestamp_seconds=_finite(row.get("timestamp_seconds")),
                    attribution=row.get("attribution"),
                    needs_review=row.get("needs_review"),
                    outcome_source=row.get("outcome_source"),
                    outcome_confidence=confidence if confidence in _CONFIDENCES else None,
                    release_timestamp_seconds=_finite(row.get("release_timestamp_seconds")),
                    resolved_timestamp_seconds=_finite(row.get("resolved_timestamp_seconds")),
                    shooter_candidates=candidates if isinstance(candidates, list) else None,
                )
            )
            # A shooter can appear without a game row (not in the players list): keep it consistent.
            games.setdefault(
                player_id,
                PlayerGameRow(player_id, job.id, job.video_id, owner, row.get("jersey_number"),
                              None, None, 0, 0, 0, 0, 0, 0, 0, 0),
            )
        if skipped:
            logger.warning("Skipped %s shot(s) of job %s with unusable numbers", skipped, job.id)
        return list(games.values()), shots, skipped


def safe_sync(sync: SyncPlayerAnalysisUseCase | None, job_id: str) -> SyncResult | None:
    """Run a sync without ever failing the caller.

    Used from the job callbacks: a problem while keeping the player numbers must not turn a
    finished analysis into an error, and the numbers can always be rebuilt later. Returns the
    result, `failed` when something raised, or None when there is no sync configured.
    """

    if sync is None:
        return None
    try:
        return sync.execute(job_id)
    except Exception:  # noqa: BLE001 - deliberately broad, see docstring
        logger.exception("Could not sync player analysis for job %s", job_id)
        return SyncResult(FAILED)


class ResyncTeamAnalysesUseCase:
    """Re-sync a team's latest analyses after its roster changed (a jersey, a player in or out).

    Who a track links to depends on the roster, so the kept rows go stale when it changes.
    Runs in the background, sequentially and best effort, bounded to the team's most recent
    analyses that have a team side. It never raises.
    """

    def __init__(self, *, jobs, sync: SyncPlayerAnalysisUseCase | None, limit: int = RESYNC_LIMIT) -> None:
        self._jobs = jobs
        self._sync = sync
        self._limit = limit

    def execute(self, team_id: str | None) -> int:
        """Returns how many analyses were re-synced successfully."""

        if not team_id or self._sync is None:
            return 0
        try:
            jobs = self._jobs.list_done_with_side_by_team(team_id=team_id, limit=self._limit)
        except Exception:  # noqa: BLE001 - never into the request, see class docstring
            logger.exception("Could not list analyses to re-sync for team %s", team_id)
            return 0
        done = 0
        for job in jobs:
            result = safe_sync(self._sync, job.id)
            if result is not None and result.status in (OK, NOT_LATEST):
                done += 1
        return done


class _PlayerReader:
    def __init__(self, players: PlayerRepositoryPort) -> None:
        self._players = players

    def check(self, *, user_id: str, player_id: str):
        player = self._players.get_by_id(player_id=player_id, owner_user_id=user_id)
        if player is None:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")
        return player


def _shot_key(row: dict) -> str:
    """Unique among all of a player's shots: shot ids only repeat across jobs, never inside one."""

    if row["shot_id"] is not None:
        return f"{row['job_id']}:{row['shot_id']}"
    return f"{row['job_id']}:row{row['id']}"


class GetPlayerShotChartUseCase:
    """Every shot a roster player took across their analysed videos, for a court diagram."""

    def __init__(self, *, players: PlayerRepositoryPort, analysis: PlayerAnalysisRepositoryPort) -> None:
        self._player = _PlayerReader(players)
        self._analysis = analysis

    def execute(self, *, user_id: str, player_id: str) -> dict:
        player = self._player.check(user_id=user_id, player_id=player_id)
        rows = self._analysis.list_shots(owner_user_id=user_id, player_id=player_id)
        shots = [
            {
                "shot_key": _shot_key(row),
                "shot_id": row["shot_id"],
                "job_id": row["job_id"],
                "video_id": row["video_id"],
                "video_title": row.get("video_title"),
                "x_m": row["court_x_m"],
                "y_m": row["court_y_m"],
                "made": row["outcome"] == MADE,
                # made draws green and missed red; unresolved is neither and stays distinct.
                "result": row["outcome"] if row["outcome"] in (MADE, MISSED) else "unknown",
                "shot_value": row["shot_value"],
                "zone": row["zone"],
                "shot_type": row["shot_type"],
                "distance_m": row["distance_m"],
                "timestamp_seconds": (
                    None if row["timestamp_seconds"] is None else round(row["timestamp_seconds"], 2)
                ),
                "outcome_confidence": row.get("outcome_confidence"),
                "outcome_source": row.get("outcome_source"),
                "release_timestamp_seconds": row.get("release_timestamp_seconds"),
                "resolved_timestamp_seconds": row.get("resolved_timestamp_seconds"),
                "attribution": row["attribution"],
                "needs_review": row["needs_review"],
            }
            for row in rows
        ]
        return {
            "player_id": player_id,
            "player": {
                "id": str(player.id),
                "first_name": player.first_name,
                "last_name": player.last_name,
                "jersey_number": player.jersey_number,
                "team_id": None if player.team_id is None else str(player.team_id),
            },
            "calc_version": CALC_VERSION,
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
        return {
            "player_id": player_id,
            "calc_version": CALC_VERSION,
            **self._analysis.totals(owner_user_id=user_id, player_id=player_id),
        }
