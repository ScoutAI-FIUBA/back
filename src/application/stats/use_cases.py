"""Read a finished job's output and answer the two questions the interface asks.

    GetGameStatsUseCase       what happened in the game
    GetCourtPositionsUseCase  where players were on the court

Both read the small structured files the pipeline wrote and do the interpretation
here, so the interface receives finished answers rather than raw analysis output.
"""

from __future__ import annotations

from src.application.jobs.errors import (
    JOB_NOT_FINISHED,
    JOB_NOT_FOUND,
    RESULTS_NOT_AVAILABLE,
    JobError,
)
from src.application.jobs.ports import JobRepositoryPort, TeamAccessPort
from src.application.stats.aggregation import (
    build_game_stats,
    number_by_track,
    team_by_track,
)
from src.application.stats.ports import ArtifactReadError, ArtifactReaderPort
from src.domain.stats.court import COURT_LENGTH_M, COURT_WIDTH_M, is_on_court
from src.domain.jobs.entities import JobStatus

SHOTS_FILE = "projected_shots.json"
TEAMS_FILE = "teams.json"
NUMBERS_FILE = "numbers.json"
# The two pipelines name their position output differently, and use a different
# key for the player identifier. A caller should not have to know which pipeline
# produced a job, so both are accepted.
POSITIONS_FILES = ("projected_tracks.jsonl", "player_positions.jsonl")
TRACK_ID_KEYS = ("track_id", "player_id")

# Upper bound on position records read for one response. A ten-second clip
# produces ~120; a full game at the same rate would be far more, and a web
# request must not try to hold all of it.
MAX_POSITION_RECORDS = 20_000


class _FinishedJobLoader:
    """Shared guard: the caller may see this job, and it has finished."""

    def __init__(self, *, jobs: JobRepositoryPort, team_access: TeamAccessPort) -> None:
        self._jobs = jobs
        self._team_access = team_access

    def load(self, *, user_id: str, team_id: str, job_id: str):
        self._team_access.assert_access(user_id=user_id, team_id=team_id)
        job = self._jobs.get_by_id(job_id=job_id, team_id=team_id)
        if job is None:
            raise JobError(code=JOB_NOT_FOUND, message="Job not found.")
        if job.status is not JobStatus.DONE:
            raise JobError(
                code=JOB_NOT_FINISHED,
                message=f"Job is {job.status.value}; statistics are not available yet.",
            )
        if not job.results_key:
            raise JobError(code=RESULTS_NOT_AVAILABLE, message="Job recorded no results location.")
        return job


class GetGameStatsUseCase:
    """The box score for one processed video."""

    def __init__(
        self,
        *,
        jobs: JobRepositoryPort,
        artifacts: ArtifactReaderPort,
        team_access: TeamAccessPort,
    ) -> None:
        self._loader = _FinishedJobLoader(jobs=jobs, team_access=team_access)
        self._artifacts = artifacts

    def execute(self, *, user_id: str, team_id: str, job_id: str) -> dict:
        job = self._loader.load(user_id=user_id, team_id=team_id, job_id=job_id)
        key = job.results_key

        try:
            shots = self._artifacts.read_json(results_key=key, filename=SHOTS_FILE)
            teams = self._artifacts.read_json(results_key=key, filename=TEAMS_FILE)
            numbers = self._artifacts.read_json(results_key=key, filename=NUMBERS_FILE)
        except ArtifactReadError as exc:
            raise JobError(code=RESULTS_NOT_AVAILABLE, message=str(exc)) from exc

        if shots is None and teams is None:
            raise JobError(
                code=RESULTS_NOT_AVAILABLE,
                message="This job produced no analysis output.",
            )

        stats = build_game_stats(
            shots_document=shots,
            teams_document=teams,
            numbers_document=numbers,
        )
        return {
            "job_id": job.id,
            "video_id": job.video_id,
            **stats.to_dict(),
        }


class GetCourtPositionsUseCase:
    """Where each tracked player was on the court, in metres.

    Returns one path per player rather than the pipeline's per-frame rows, since
    that is what a court diagram or heatmap actually draws.
    """

    def __init__(
        self,
        *,
        jobs: JobRepositoryPort,
        artifacts: ArtifactReaderPort,
        team_access: TeamAccessPort,
    ) -> None:
        self._loader = _FinishedJobLoader(jobs=jobs, team_access=team_access)
        self._artifacts = artifacts

    def execute(
        self, *, user_id: str, team_id: str, job_id: str, sample_every: int = 1
    ) -> dict:
        job = self._loader.load(user_id=user_id, team_id=team_id, job_id=job_id)
        key = job.results_key

        rows: list[dict] = []
        source_file: str | None = None
        try:
            for candidate in POSITIONS_FILES:
                rows = self._artifacts.read_jsonl(
                    results_key=key, filename=candidate, max_lines=MAX_POSITION_RECORDS
                )
                if rows:
                    source_file = candidate
                    break
        except ArtifactReadError as exc:
            raise JobError(code=RESULTS_NOT_AVAILABLE, message=str(exc)) from exc

        teams_document = self._artifacts.read_json(results_key=key, filename=TEAMS_FILE)
        numbers_document = self._artifacts.read_json(results_key=key, filename=NUMBERS_FILE)
        teams_of = team_by_track(teams_document)
        numbers_of = number_by_track(numbers_document)

        sample_every = max(1, int(sample_every))
        paths: dict[int, dict] = {}
        discarded = 0
        seen_per_track: dict[int, int] = {}

        for row in rows:
            court_xy = row.get("court_xy_m")
            track_id = next(
                (row[key_] for key_ in TRACK_ID_KEYS if row.get(key_) is not None), None
            )
            if track_id is None or not court_xy or len(court_xy) < 2:
                continue

            # Bad homography can throw a player far off the court; those points
            # would distort a heatmap badly, so they are dropped rather than drawn.
            if not is_on_court((court_xy[0], court_xy[1])):
                discarded += 1
                continue

            track_id = int(track_id)
            index = seen_per_track.get(track_id, 0)
            seen_per_track[track_id] = index + 1
            if index % sample_every:
                continue

            path = paths.setdefault(
                track_id,
                {
                    "track_id": track_id,
                    # player_positions rows carry the team directly; the stats
                    # pipeline's rows do not, so fall back to the assignments file.
                    "team_id": row.get("team_id", teams_of.get(track_id)),
                    "jersey_number": numbers_of.get(track_id),
                    "positions": [],
                },
            )
            path["positions"].append(
                {
                    "frame_index": row.get("frame_index"),
                    "x_m": round(float(court_xy[0]), 2),
                    "y_m": round(float(court_xy[1]), 2),
                }
            )

        return {
            "job_id": job.id,
            "video_id": job.video_id,
            "court": {"length_m": COURT_LENGTH_M, "width_m": COURT_WIDTH_M},
            "players": [paths[key_] for key_ in sorted(paths)],
            "coverage": {
                "source_file": source_file,
                "records_read": len(rows),
                "records_off_court": discarded,
                "sample_every": sample_every,
                "truncated": len(rows) >= MAX_POSITION_RECORDS,
            },
        }
