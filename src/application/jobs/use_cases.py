from __future__ import annotations

from collections.abc import Callable

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.application.jobs.errors import (
    INVALID_JOB_STATUS,
    JOB_NOT_FINISHED,
    RESULTS_NOT_AVAILABLE,
    STORAGE_NOT_CONFIGURED,
    JOB_ALREADY_ACTIVE,
    JOB_NOT_FOUND,
    PROCESSING_SERVICE_UNAVAILABLE,
    VIDEO_NOT_FOUND,
    VIDEO_NOT_READY,
    JobError,
)
from src.application.jobs.ports import (
    ActiveJobExistsError,
    ArtifactUrlSignerPort,
    ArtifactUrlsUnavailableError,
    IdGeneratorPort,
    JobRepositoryPort,
    ProcessingServiceError,
    ProcessingServicePort,
    TeamAccessPort,
    UnitOfWorkPort,
    VideoLookupPort,
)
from src.domain.jobs.entities import JobStatus, ProcessingJob

# Where a job's outputs are written, mirroring the `videos/{team_id}/{id}`
# convention already used for uploads.
RESULTS_KEY_TEMPLATE = "results/{team_id}/{job_id}"

# A worker can die (Modal timeout, crash) without sending a terminal callback,
# leaving a job RUNNING forever and blocking its video. A live worker reports
# progress every few seconds, so an active job whose last update (`updated_at`)
# is older than this heartbeat window is treated as dead.
STALE_ACTIVE_JOB_HEARTBEAT = timedelta(minutes=15)
# Backstop for a worker that keeps heartbeating but never finishes: no job may
# stay active longer than this since it started (or was created, if never started).
STALE_ACTIVE_JOB_MAX_RUNTIME = timedelta(minutes=75)
STALE_JOB_ERROR_MESSAGE = "Job stopped reporting progress; marked stale."


def _as_utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _is_stale_active_job(job: ProcessingJob) -> bool:
    if not job.status.is_active:
        return False
    now = datetime.now(timezone.utc)
    if job.updated_at is not None and now - _as_utc(job.updated_at) > STALE_ACTIVE_JOB_HEARTBEAT:
        return True
    started = job.started_at or job.created_at
    return started is not None and now - _as_utc(started) > STALE_ACTIVE_JOB_MAX_RUNTIME


def _retire_if_stale(jobs: JobRepositoryPort, uow: UnitOfWorkPort | None, job: ProcessingJob) -> ProcessingJob:
    """Fail `job` when it is a stale active job; otherwise return it unchanged.

    Idempotent: the repository only fails a still-active job, so a job that
    finished meanwhile (or was already retired) comes back as it is stored.
    """
    if not _is_stale_active_job(job):
        return job
    if uow is not None:
        with uow.transaction():
            failed = jobs.mark_failed(job_id=job.id, error_message=STALE_JOB_ERROR_MESSAGE)
    else:
        failed = jobs.mark_failed(job_id=job.id, error_message=STALE_JOB_ERROR_MESSAGE)
    return failed or job


@dataclass(frozen=True)
class SubmitProcessingJobCommand:
    user_id: str
    team_id: str
    video_id: str
    # Which analysis the processing service should run. None means "its default".
    # This app does not enumerate the choices, so adding a pipeline on the
    # processing side needs no change here.
    pipeline: str | None = None


class SubmitProcessingJobUseCase:
    """Queue one video for processing and hand it to the GPU service.

    Returns as soon as the service acknowledges. It never waits for processing
    to finish — a full game takes hours, and an HTTP request must not.
    """

    def __init__(
        self,
        *,
        jobs: JobRepositoryPort,
        videos: VideoLookupPort,
        processing: ProcessingServicePort,
        team_access: TeamAccessPort,
        ids: IdGeneratorPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._jobs = jobs
        self._videos = videos
        self._processing = processing
        self._team_access = team_access
        self._ids = ids
        self._uow = uow

    def execute(self, command: SubmitProcessingJobCommand) -> ProcessingJob:
        self._team_access.assert_access(user_id=command.user_id, team_id=command.team_id)

        video = self._videos.get_ready_video(video_id=command.video_id, team_id=command.team_id)
        if video is None:
            # Distinguish "no such video" from "exists but upload not finished",
            # so the client knows whether to retry later or fix the id.
            if self._videos.exists(video_id=command.video_id, team_id=command.team_id):
                raise JobError(
                    code=VIDEO_NOT_READY,
                    message="Video upload has not completed, so it cannot be processed yet.",
                )
            raise JobError(code=VIDEO_NOT_FOUND, message="Video not found.")

        _, storage_key = video

        # Submitting is idempotent per video: if a live job is already processing
        # this video, hand it back so the client just navigates to its screen —
        # never an error. A dead job (worker died without a terminal callback) is
        # retired first so it cannot block the video forever.
        active = self._jobs.find_active_for_video(video_id=command.video_id)
        if active is not None:
            if _is_stale_active_job(active):
                self._jobs.mark_failed(job_id=active.id, error_message=STALE_JOB_ERROR_MESSAGE)
            else:
                return active

        job_id = self._ids.new_id()
        results_key = RESULTS_KEY_TEMPLATE.format(team_id=command.team_id, job_id=job_id)

        # The row is committed before the service is called. If the call then
        # fails we mark the job FAILED below; the alternative (call first) risks
        # spending GPU time on a job with no record of it.
        try:
            with self._uow.transaction():
                job = self._jobs.create_queued(
                    job_id=job_id,
                    video_id=command.video_id,
                    team_id=command.team_id,
                    requested_by_user_id=command.user_id,
                    # Stored up front, not on completion: the client needs to
                    # know where results will land, and the processing service
                    # is told the same prefix below.
                    results_key=results_key,
                )
        except ActiveJobExistsError as exc:
            # Lost a race: another request created the job between our check and
            # this insert. Hand back that job rather than erroring, keeping submit
            # idempotent.
            existing = self._jobs.find_active_for_video(video_id=command.video_id)
            if existing is not None:
                return existing
            raise JobError(
                code=JOB_ALREADY_ACTIVE,
                message="This video already has a job queued or running.",
            ) from exc

        try:
            submitted = self._processing.submit(
                job_id=job.id,
                video_storage_key=storage_key,
                results_key=results_key,
                pipeline=command.pipeline,
            )
        except ProcessingServiceError as exc:
            # Leaving the row QUEUED would block every future submission for this
            # video, because of the one-active-job index. Fail it explicitly.
            with self._uow.transaction():
                self._jobs.mark_failed(job_id=job.id, error_message=str(exc))
            raise JobError(
                code=PROCESSING_SERVICE_UNAVAILABLE,
                message="Could not reach the processing service. The job was not started.",
            ) from exc

        with self._uow.transaction():
            updated = self._jobs.attach_external_id(
                job_id=job.id, external_job_id=submitted.external_job_id
            )
        return updated or job


@dataclass(frozen=True)
class RecordJobProgressCommand:
    """A status report from the processing service about one job."""

    job_id: str
    status: JobStatus
    results_key: str | None = None
    error_message: str | None = None
    progress_percent: int | None = None
    progress_phase: str | None = None
    # What the service wrote, reported on completion so this app never has to
    # list or read the object store to find out.
    artifacts: list[str] | None = None
    summary: dict | None = None


class RecordJobProgressUseCase:
    """Apply a status callback from the processing service.

    Authenticated by a shared service token at the transport layer, so there is
    no user or team context here — the job is looked up by id alone.

    Idempotent by design. The service may retry a callback, or deliver two out of
    order, and neither should corrupt a finished job: once a job is DONE or
    FAILED its outcome is fixed and later reports are ignored rather than
    rejected. Returning the job unchanged keeps retries cheap and quiet.
    """

    def __init__(
        self,
        *,
        jobs: JobRepositoryPort,
        uow: UnitOfWorkPort,
        on_done: Callable[[ProcessingJob], None] | None = None,
    ) -> None:
        self._jobs = jobs
        self._uow = uow
        # Called once, after the commit, with the job that just finished. It must not raise.
        self._on_done = on_done

    def execute(self, command: RecordJobProgressCommand) -> ProcessingJob:
        job = self._jobs.get_by_id_unscoped(job_id=command.job_id)
        if job is None:
            raise JobError(code=JOB_NOT_FOUND, message="Job not found.")

        if job.status.is_terminal:
            # Already finished. A late or duplicate callback must not resurrect
            # it or overwrite the recorded outcome.
            return job

        with self._uow.transaction():
            if command.status is JobStatus.RUNNING:
                updated = self._jobs.mark_running(
                    job_id=command.job_id,
                    progress_percent=command.progress_percent,
                    progress_phase=command.progress_phase,
                )
            elif command.status is JobStatus.DONE:
                updated = self._jobs.mark_done(
                    job_id=command.job_id,
                    results_key=command.results_key,
                    artifacts=command.artifacts,
                    summary=command.summary,
                )
            elif command.status is JobStatus.FAILED:
                updated = self._jobs.mark_failed(
                    job_id=command.job_id,
                    error_message=command.error_message or "Processing failed.",
                )
            else:
                # QUEUED is set by this service at submission; the processing
                # side has no reason to report it back.
                raise JobError(
                    code=INVALID_JOB_STATUS,
                    message=f"Cannot report status {command.status.value} for a job.",
                )
        if command.status is JobStatus.DONE and self._on_done is not None and updated is not None:
            self._on_done(updated)
        return updated or job


class GetProcessingJobUseCase:
    """Poll one job. A stale active job is retired here, so polling never shows a dead job as running."""

    def __init__(
        self, *, jobs: JobRepositoryPort, team_access: TeamAccessPort, uow: UnitOfWorkPort | None = None
    ) -> None:
        self._jobs = jobs
        self._team_access = team_access
        self._uow = uow

    def execute(self, *, user_id: str, team_id: str, job_id: str) -> ProcessingJob:
        self._team_access.assert_access(user_id=user_id, team_id=team_id)
        job = self._jobs.get_by_id(job_id=job_id, team_id=team_id)
        if job is None:
            raise JobError(code=JOB_NOT_FOUND, message="Job not found.")
        return _retire_if_stale(self._jobs, self._uow, job)


class SetJobTeamSideUseCase:
    """Record which pipeline side (0 or 1) is the scout's own team.

    Chosen once per job after processing; it is what lets a track be tied back to
    a roster player by jersey number.
    """

    def __init__(
        self,
        *,
        jobs: JobRepositoryPort,
        team_access: TeamAccessPort,
        on_changed: Callable[[ProcessingJob], None] | None = None,
    ) -> None:
        self._jobs = jobs
        self._team_access = team_access
        # Called after the side is stored, with the updated job. It must not raise.
        self._on_changed = on_changed

    def execute(self, *, user_id: str, team_id: str, job_id: str, our_team_side: int) -> ProcessingJob:
        self._team_access.assert_access(user_id=user_id, team_id=team_id)
        job = self._jobs.set_our_team_side(
            job_id=job_id, team_id=team_id, our_team_side=our_team_side
        )
        if job is None:
            raise JobError(code=JOB_NOT_FOUND, message="Job not found.")
        if self._on_changed is not None:
            self._on_changed(job)
        return job


# How long a results download link stays valid. Long enough to load the analysis
# files, short enough that a leaked URL stops working the same day.
RESULTS_URL_TTL_SECONDS = 3600


class GetJobResultsUseCase:
    """Return a finished job's summary plus download links for its artifacts.

    This app never reads a job's outputs. The processing service reports what it
    wrote when it finishes, and that list is stored on the job; here it is simply
    turned into presigned URLs. Signing is local — no request is made to the
    object store — so this endpoint stays fast and keeps working even when
    storage is slow.

    The summary comes back inline because it is small and the UI wants it
    immediately; everything else is fetched by the browser directly.
    """

    def __init__(
        self,
        *,
        jobs: JobRepositoryPort,
        urls: ArtifactUrlSignerPort,
        team_access: TeamAccessPort,
    ) -> None:
        self._jobs = jobs
        self._urls = urls
        self._team_access = team_access

    def execute(self, *, user_id: str, team_id: str, job_id: str) -> dict:
        self._team_access.assert_access(user_id=user_id, team_id=team_id)

        job = self._jobs.get_by_id(job_id=job_id, team_id=team_id)
        if job is None:
            raise JobError(code=JOB_NOT_FOUND, message="Job not found.")

        if job.status is not JobStatus.DONE:
            # Deliberately a 409 rather than an empty 200: a client that asks
            # for results early has made a sequencing mistake and should keep
            # polling, not render a blank analysis.
            raise JobError(
                code=JOB_NOT_FINISHED,
                message=f"Job is {job.status.value}; results are not available yet.",
            )

        if not job.results_key:
            raise JobError(code=RESULTS_NOT_AVAILABLE, message="Job recorded no results location.")

        prefix = job.results_key.rstrip("/")
        # Keyed by filename so the client can ask for what it needs
        # ("projected_shots.json") without this app knowing what any of them mean.
        try:
            artifact_urls = {
                filename: self._urls.presign(
                    key=f"{prefix}/{filename}", expires_in=RESULTS_URL_TTL_SECONDS
                )
                for filename in sorted(job.artifacts or [])
            }
        except ArtifactUrlsUnavailableError as exc:
            raise JobError(code=STORAGE_NOT_CONFIGURED, message=str(exc)) from exc

        return {
            "job_id": job.id,
            "video_id": job.video_id,
            "results_key": job.results_key,
            "summary": job.summary,
            "artifact_urls": artifact_urls,
            "expires_in_seconds": RESULTS_URL_TTL_SECONDS,
        }


class ListVideoJobsUseCase:
    def __init__(
        self, *, jobs: JobRepositoryPort, team_access: TeamAccessPort, uow: UnitOfWorkPort | None = None
    ) -> None:
        self._jobs = jobs
        self._team_access = team_access
        self._uow = uow

    def execute(self, *, user_id: str, team_id: str, video_id: str) -> list[ProcessingJob]:
        self._team_access.assert_access(user_id=user_id, team_id=team_id)
        jobs = self._jobs.list_by_video(video_id=video_id, team_id=team_id)
        return [_retire_if_stale(self._jobs, self._uow, job) for job in jobs]
