"""Keeps what the analyses measured for each roster player, and serves it back.

`SyncPlayerAnalysisUseCase` runs when a job finishes and when the scout marks which side is
their team. It reuses the very computation behind the per-video box score, so the persisted
numbers are that box score as it was at the moment of the last sync. `CatchUpPlayerAnalysisUseCase`
keeps them current by itself: each finished analysis carries a marker saying its player stats
are done, and the catch-up runs the sync for every analysis without it (at startup, after a
players listing finds something pending, and after a roster change clears a team's markers).
The read use cases then answer across all of a player's videos: aggregated totals and every
shot's court position, ready to draw as green and red dots.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from src.application.stats.ports import ArtifactReaderPort, ArtifactStorageError
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
STALE = "stale"
NO_SIDE = "no_side"
NOT_READY = "not_ready"
JOB_NOT_FOUND = "job_not_found"

# Public name of a `stale` result in the team-side response: like a changed side, nothing was kept
# and the work is redone automatically.
PUBLIC_STATUS = {STALE: SIDE_CHANGED}

# Values the table accepts for `outcome_confidence`; anything else is stored as unknown.
_CONFIDENCES = frozenset({"detected", "inferred", "timeout", "unresolved"})

# How many pending analyses one catch-up run keeps (newest first; the rest wait for the next run).
CATCH_UP_LIMIT = 200
# A user's listing checks for pending work at most this often.
PENDING_CHECK_SECONDS = 60.0
# A job whose sync failed is not retried for this long (e.g. result files missing in storage).
FAILURE_MEMO_SECONDS = 600.0


@dataclass(frozen=True)
class ReplaceResult:
    """What `replace_video` did: `ok`, or `not_latest`, `side_changed` or `stale` (nothing was changed)."""

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
        started: datetime | None = None,
    ) -> ReplaceResult:
        """Replace everything kept for a video and refresh the affected players' totals.

        Serialised per video. Inside that lock it re-checks that `job_id` is still the latest
        DONE job of the video and that the job's team side is still `expected_side`; if not,
        nothing is changed and the status says why. The job's "player stats done" marker is only set
        when it was not cleared after `started` (the database clock read before the sync began).
        """

    @abstractmethod
    def database_now(self) -> datetime:
        """The database clock, the same one that stamps marker changes."""

    @abstractmethod
    def mark_superseded(self, *, video_id: str, job_id: str, started: datetime | None = None) -> bool:
        """Mark an older analysis of a video as done (the newer one decides). False when it is not older."""

    @abstractmethod
    def refresh_players_for_video(self, video_id: str) -> list[str]:
        """Recompute the totals of every player that has rows for the video (soft-deleted videos excluded)."""

    @abstractmethod
    def list_shots(self, *, owner_user_id: str, player_id: str) -> list[dict]:
        """Every kept shot of a player, oldest video first, each with its row `id`."""

    @abstractmethod
    def totals(self, *, owner_user_id: str, player_id: str) -> dict:
        """Aggregated totals, per-zone and per-shot-type tallies and the list of games."""


class _RecordingReader(ArtifactReaderPort):
    """Delegates to the real reader and remembers whether storage itself failed on any read.

    One per sync, so its state is private to that call (and to its thread).
    """

    def __init__(self, inner: ArtifactReaderPort) -> None:
        self._inner = inner
        self.storage_failures: list[ArtifactStorageError] = []

    def _call(self, method, **kwargs):
        try:
            return method(**kwargs)
        except ArtifactStorageError as exc:
            self.storage_failures.append(exc)
            raise

    def read_json(self, *, results_key: str, filename: str) -> dict | None:
        return self._call(self._inner.read_json, results_key=results_key, filename=filename)

    def read_jsonl(self, *, results_key: str, filename: str, max_lines: int) -> list[dict]:
        return self._call(self._inner.read_jsonl, results_key=results_key, filename=filename, max_lines=max_lines)


def strict_game_stats_reader(*, jobs, artifacts: ArtifactReaderPort, team_access, roster) -> GameStatsReader:
    """The box score for the sync: the same computation, but a storage failure on ANY file fails it.

    The screens tolerate a missing optional file (player_summary.json, results.json, positions) and
    degrade; the sync must not, because a degraded answer links fewer players and would shrink the
    kept rows. Only the sync uses this; the endpoints keep their graceful degradation.
    """

    from src.application.stats.use_cases import GetGameStatsUseCase

    def read(**kwargs) -> dict:
        recording = _RecordingReader(artifacts)
        stats = GetGameStatsUseCase(
            jobs=jobs, artifacts=recording, team_access=team_access, roster=roster
        ).execute(**kwargs)
        if recording.storage_failures:
            raise ArtifactStorageError("Object storage failed while reading this analysis; not keeping a partial answer.")
        return stats

    return read


class CatchUpLockPort(ABC):
    """One catch-up at a time across every worker and instance."""

    @abstractmethod
    def try_acquire(self) -> AbstractContextManager[bool]:
        """Yields True while this caller holds the lock, False at once when someone else does."""


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

        # Before anything is read: a roster change after this instant must keep the result from counting as done.
        started = self._analysis.database_now()
        job = self._jobs.get_by_id_unscoped(job_id=job_id)
        if job is None:
            return SyncResult(JOB_NOT_FOUND)
        if job.status is not JobStatus.DONE or not job.results_key:
            return SyncResult(NOT_READY)
        if not self._is_latest_done_for_video(job):
            # An older analysis of a video that has a newer one: the newer one decides.
            self._analysis.mark_superseded(video_id=job.video_id, job_id=job.id, started=started)
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
            video_id=job.video_id, job_id=job.id, expected_side=side, games=games, shots=shots, started=started
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


def safe_sync(
    sync: SyncPlayerAnalysisUseCase | None, job_id: str, *, log_level: int = logging.ERROR
) -> SyncResult | None:
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
        logger.log(log_level, "Could not sync player analysis for job %s", job_id, exc_info=True)
        return SyncResult(FAILED)


class CatchUpPlayerAnalysisUseCase:
    """Brings the kept player numbers up to date for every analysis not marked as done.

    The marker is written by the sync itself, in the same transaction as the rows, so "unmarked"
    means "not kept yet with the current rules": it covers analyses that predate the feature,
    syncs that failed, and a team whose markers a roster change cleared. Runs in the background
    (startup, after a players listing, after a roster change), one run at a time across
    instances, sequentially and best effort. It never raises into its caller.
    """

    def __init__(
        self,
        *,
        jobs,
        sync: SyncPlayerAnalysisUseCase | None,
        lock: CatchUpLockPort | None = None,
        clock: Callable[[], float] = time.monotonic,
        pending_check_seconds: float = PENDING_CHECK_SECONDS,
        failure_memo_seconds: float = FAILURE_MEMO_SECONDS,
    ) -> None:
        self._jobs = jobs
        self._sync = sync
        self._lock = lock
        self._clock = clock
        self._pending_check_seconds = pending_check_seconds
        self._failure_memo_seconds = failure_memo_seconds
        # Shared by request threads and the background runs.
        self._state = threading.Lock()
        self._in_flight: set[str] = set()
        self._failed_until: dict[str, float] = {}
        self._checked_at: dict[str, float] = {}
        self._failed_before: set[str] = set()  # jobs already reported once: their retries are only debug noise

    def pending(self, user_id: str) -> bool:
        """Whether the user has analyses to catch up on; asks the database once per window per user.

        Inside the window it answers False: whatever was found by the last check is already
        scheduled. A failure to ask also answers False.
        """

        now = self._clock()
        with self._state:
            last = self._checked_at.get(user_id)
            if last is not None and now - last < self._pending_check_seconds:
                return False
            self._checked_at[user_id] = now
            if len(self._checked_at) > 1000:
                self._checked_at = {
                    key: at for key, at in self._checked_at.items() if now - at < self._pending_check_seconds
                }
            self._forget_expired_failures(now)
            skipped = len(self._failed_until)
            blocked = set(self._failed_until)
        try:
            found = self._jobs.list_player_stats_pending(
                user_id=user_id, team_id=None, version=CALC_VERSION, limit=skipped + 1
            )
        except Exception:  # noqa: BLE001 - never into the request
            logger.exception("Could not check pending player stats for user %s", user_id)
            return False
        return any(job.id not in blocked for job in found)

    def invalidate_team(self, team_id: str | None) -> None:
        """Forget that the team's analyses were kept (its roster changed). Never raises."""

        if not team_id:
            return
        try:
            self._jobs.clear_player_stats_synced(team_id=team_id)
        except Exception:  # noqa: BLE001 - never into the request
            logger.exception("Could not clear player stats markers for team %s", team_id)

    def execute(
        self, user_id: str | None = None, team_id: str | None = None, limit: int = CATCH_UP_LIMIT
    ) -> int:
        """Sync the pending analyses (of a user and/or a team, or all) one after another.

        Returns how many are now done. Skips the whole run when another one holds the lock.
        """

        if self._sync is None:
            return 0
        try:
            if self._lock is None:
                return self._run(user_id, team_id, limit)
            with self._lock.try_acquire() as acquired:
                if not acquired:
                    return 0
                return self._run(user_id, team_id, limit)
        except Exception:  # noqa: BLE001 - never into the request or the startup, see class docstring
            logger.exception("Player stats catch-up failed (user=%s, team=%s)", user_id, team_id)
            return 0

    def _run(self, user_id: str | None, team_id: str | None, limit: int) -> int:
        jobs = self._jobs.list_player_stats_pending(
            user_id=user_id, team_id=team_id, version=CALC_VERSION, limit=limit
        )
        done = 0
        for job in jobs:
            if not self._begin(job.id):
                continue
            try:
                result = safe_sync(self._sync, job.id, log_level=self._failure_log_level(job.id))
            finally:
                self._end(job.id)
            if result is None:
                continue
            if result.status == FAILED:
                self._remember_failure(job.id)
            elif result.status in (OK, NOT_LATEST, NO_SIDE):
                done += 1
        return done

    def _begin(self, job_id: str) -> bool:
        """False when the job is being synced right now or failed recently."""

        now = self._clock()
        with self._state:
            self._forget_expired_failures(now)
            if job_id in self._in_flight or job_id in self._failed_until:
                return False
            self._in_flight.add(job_id)
            return True

    def _end(self, job_id: str) -> None:
        with self._state:
            self._in_flight.discard(job_id)

    def _failure_log_level(self, job_id: str) -> int:
        """WARNING the first time a job fails, DEBUG for its retries (a broken analysis must not spam the logs)."""

        with self._state:
            return logging.DEBUG if job_id in self._failed_before else logging.WARNING

    def _remember_failure(self, job_id: str) -> None:
        with self._state:
            if len(self._failed_before) > 10_000:
                self._failed_before.clear()
            self._failed_before.add(job_id)
            self._failed_until[job_id] = self._clock() + self._failure_memo_seconds

    def _forget_expired_failures(self, now: float) -> None:
        """Caller holds `_state`."""

        for job_id in [key for key, until in self._failed_until.items() if until <= now]:
            del self._failed_until[job_id]


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
