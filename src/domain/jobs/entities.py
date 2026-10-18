from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle of one video-processing job.

    QUEUED   accepted and handed to the processing service, not yet started
    RUNNING  the service reported it has begun
    DONE     finished; `results_key` points at the output
    FAILED   finished unsuccessfully; `error_message` explains why
    """

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.DONE, JobStatus.FAILED)

    @property
    def is_active(self) -> bool:
        return not self.is_terminal


@dataclass(frozen=True)
class ProcessingJob:
    id: str
    video_id: str
    team_id: str
    requested_by_user_id: str
    status: JobStatus
    external_job_id: str | None
    results_key: str | None
    error_message: str | None
    progress_percent: int | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Reported by the processing service on completion; absent until then.
    artifacts: list[str] | None = None
    summary: dict | None = None
    # Which pipeline side (0 or 1) is the scout's own team, chosen after
    # processing. The pipeline splits players into two colourless sides; this is
    # how a track gets tied back to a roster player by jersey number. None until
    # the scout picks a side.
    our_team_side: int | None = None
    # Cached clip-similarity feature vector, computed once from the output and
    # reused so comparing clips never re-reads storage. None until first needed.
    features: dict | None = None
    # Which pipeline phase the service last reported (e.g. "tracking"), so the UI
    # can say what the job is doing. Only meaningful while active: cleared on
    # DONE and FAILED. None until the service reports one.
    progress_phase: str | None = None
