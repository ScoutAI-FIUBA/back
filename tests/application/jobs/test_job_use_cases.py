from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from src.application.jobs.errors import (
    INVALID_JOB_STATUS,
    JOB_NOT_FINISHED,
    RESULTS_NOT_AVAILABLE,
    JOB_ALREADY_ACTIVE,
    JOB_NOT_FOUND,
    PROCESSING_SERVICE_UNAVAILABLE,
    VIDEO_NOT_FOUND,
    VIDEO_NOT_READY,
    JobError,
)
from src.application.jobs.ports import (
    ActiveJobExistsError,
    ProcessingServiceError,
    SubmittedJob,
)
from src.application.jobs.use_cases import (
    GetJobResultsUseCase,
    GetProcessingJobUseCase,
    ListVideoJobsUseCase,
    RecordJobProgressCommand,
    RecordJobProgressUseCase,
    SetJobTeamSideUseCase,
    SubmitProcessingJobCommand,
    STALE_ACTIVE_JOB_HEARTBEAT,
    STALE_ACTIVE_JOB_MAX_RUNTIME,
    STALE_JOB_ERROR_MESSAGE,
    SubmitProcessingJobUseCase,
)
from src.domain.jobs.entities import JobStatus, ProcessingJob

USER_ID = "user-1"
TEAM_ID = "11111111-1111-1111-1111-111111111111"
VIDEO_ID = "22222222-2222-2222-2222-222222222222"
JOB_ID = "33333333-3333-3333-3333-333333333333"
STORAGE_KEY = f"videos/{TEAM_ID}/{VIDEO_ID}"


def build_job(status: JobStatus = JobStatus.QUEUED, **overrides) -> ProcessingJob:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": JOB_ID,
        "video_id": VIDEO_ID,
        "team_id": TEAM_ID,
        "requested_by_user_id": USER_ID,
        "status": status,
        "external_job_id": None,
        "results_key": None,
        "error_message": None,
        "progress_percent": None,
        "started_at": None,
        "finished_at": None,
        "created_at": now,
        "updated_at": now,
    }
    return ProcessingJob(**{**defaults, **overrides})


class FakeJobRepository:
    def __init__(self, *, raise_active: bool = False) -> None:
        self.raise_active = raise_active
        self.jobs: dict[str, ProcessingJob] = {}
        self.failed_with: list[tuple[str, str]] = []

    def create_queued(self, *, job_id, video_id, team_id, requested_by_user_id, results_key):
        if self.raise_active:
            raise ActiveJobExistsError("already active")
        job = build_job(id=job_id, video_id=video_id, team_id=team_id,
                        requested_by_user_id=requested_by_user_id, results_key=results_key)
        self.jobs[job_id] = job
        return job

    def attach_external_id(self, *, job_id, external_job_id):
        job = self.jobs.get(job_id)
        if job is None:
            return None
        updated = build_job(
            id=job.id, external_job_id=external_job_id, results_key=job.results_key
        )
        self.jobs[job_id] = updated
        return updated

    def mark_failed(self, *, job_id, error_message):
        existing = self.jobs.get(job_id)
        if existing is not None and existing.status.is_terminal:
            return None
        self.failed_with.append((job_id, error_message))
        job = build_job(id=job_id, status=JobStatus.FAILED, error_message=error_message)
        self.jobs[job_id] = job
        return job

    def get_by_id(self, *, job_id, team_id):
        return self.jobs.get(job_id)

    def get_by_id_unscoped(self, *, job_id):
        return self.jobs.get(job_id)

    def mark_running(self, *, job_id, progress_percent, progress_phase=None):
        # Mirrors the SQL: progress only moves forward, a missing phase keeps the old one.
        previous = self.jobs.get(job_id)
        old_percent = previous.progress_percent if previous else None
        old_phase = previous.progress_phase if previous else None
        percent = max((v for v in (old_percent, progress_percent) if v is not None), default=None)
        job = build_job(id=job_id, status=JobStatus.RUNNING, progress_percent=percent,
                        progress_phase=progress_phase or old_phase)
        self.jobs[job_id] = job
        return job

    def mark_done(self, *, job_id, results_key, artifacts=None, summary=None):
        job = build_job(id=job_id, status=JobStatus.DONE, results_key=results_key,
                        progress_percent=100, artifacts=artifacts, summary=summary)
        self.jobs[job_id] = job
        return job

    def list_by_video(self, *, video_id, team_id):
        return [j for j in self.jobs.values() if j.video_id == video_id]

    def set_our_team_side(self, *, job_id, team_id, our_team_side):
        job = self.jobs.get(job_id)
        if job is None:
            return None
        updated = replace(job, our_team_side=our_team_side)
        self.jobs[job_id] = updated
        return updated

    def find_active_for_video(self, *, video_id):
        return next((j for j in self.jobs.values() if j.video_id == video_id and j.status.is_active), None)


class FakeVideoLookup:
    def __init__(self, *, ready: bool = True, present: bool = True) -> None:
        self.ready = ready
        self.present = present

    def get_ready_video(self, *, video_id, team_id):
        return (video_id, STORAGE_KEY) if (self.present and self.ready) else None

    def exists(self, *, video_id, team_id):
        return self.present


class FakeProcessingService:
    """Stands in for the GPU service, which need not exist to develop this."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    def submit(self, *, job_id, video_storage_key, results_key, pipeline=None):
        self.calls.append(
            {
                "job_id": job_id,
                "video_storage_key": video_storage_key,
                "results_key": results_key,
                "pipeline": pipeline,
            }
        )
        if self.fail:
            raise ProcessingServiceError("connection refused")
        return SubmittedJob(external_job_id=f"ext-{job_id}")


class FakeTeamAccess:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed

    def assert_access(self, *, user_id, team_id):
        if not self.allowed:
            raise JobError(code="FORBIDDEN_TEAM_ACCESS", message="no access")


class FakeIds:
    def new_id(self) -> str:
        return JOB_ID


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.transactions = 0

    def transaction(self):
        outer = self

        class _Tx:
            def __enter__(self):
                outer.transactions += 1
                return None

            def __exit__(self, *exc_info):
                return False

        return _Tx()


def build_submit(**kwargs) -> tuple[SubmitProcessingJobUseCase, dict]:
    parts = {
        "jobs": FakeJobRepository(),
        "videos": FakeVideoLookup(),
        "processing": FakeProcessingService(),
        "team_access": FakeTeamAccess(),
        "ids": FakeIds(),
        "uow": FakeUnitOfWork(),
    }
    parts.update(kwargs)
    return SubmitProcessingJobUseCase(**parts), parts


class TestSubmitProcessingJob(unittest.TestCase):
    def test_queues_job_and_returns_external_id(self) -> None:
        use_case, parts = build_submit()
        job = use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))

        self.assertEqual(job.id, JOB_ID)
        self.assertEqual(job.external_job_id, f"ext-{JOB_ID}")
        self.assertEqual(job.status, JobStatus.QUEUED)

    def test_passes_storage_key_and_results_prefix_to_service(self) -> None:
        use_case, parts = build_submit()
        use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))

        call = parts["processing"].calls[0]
        self.assertEqual(call["video_storage_key"], STORAGE_KEY)
        self.assertEqual(call["results_key"], f"results/{TEAM_ID}/{JOB_ID}")

    def test_results_key_is_persisted_so_clients_can_find_output(self) -> None:
        """Without this the client polls a job that never says where results are."""

        use_case, _ = build_submit()
        job = use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertEqual(job.results_key, f"results/{TEAM_ID}/{JOB_ID}")

    def test_missing_video_is_not_found(self) -> None:
        use_case, _ = build_submit(videos=FakeVideoLookup(present=False, ready=False))
        with self.assertRaises(JobError) as ctx:
            use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertEqual(ctx.exception.code, VIDEO_NOT_FOUND)

    def test_video_still_uploading_is_reported_separately(self) -> None:
        """A client that gets NOT_READY should retry; NOT_FOUND means fix the id."""

        use_case, _ = build_submit(videos=FakeVideoLookup(present=True, ready=False))
        with self.assertRaises(JobError) as ctx:
            use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertEqual(ctx.exception.code, VIDEO_NOT_READY)

    def test_a_live_active_job_is_returned_not_duplicated(self) -> None:
        """Submitting a video with a live job hands that job back (navigable), not a 409.

        Idempotent per video: no duplicate GPU spend, and the client gets a job to
        open rather than an error.
        """

        jobs = FakeJobRepository(raise_active=True)
        jobs.jobs["old"] = build_job(
            id="old", status=JobStatus.RUNNING, updated_at=datetime.now(timezone.utc)
        )
        use_case, parts = build_submit(jobs=jobs)
        job = use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertEqual(job.id, "old")  # handed back the in-flight job
        self.assertEqual(jobs.failed_with, [])  # not retired
        self.assertEqual(parts["processing"].calls, [])  # not resubmitted to the GPU

    def test_409_only_when_an_active_job_exists_but_cannot_be_read_back(self) -> None:
        """Fallback: the index rejects the insert yet we can't find the active row."""

        use_case, _ = build_submit(jobs=FakeJobRepository(raise_active=True))
        with self.assertRaises(JobError) as ctx:
            use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertEqual(ctx.exception.code, JOB_ALREADY_ACTIVE)

    def test_a_stale_active_job_is_retired_so_a_new_one_can_run(self) -> None:
        """A job whose worker died without a callback must not block the video forever."""

        jobs = FakeJobRepository()
        stale = datetime.now(timezone.utc) - timedelta(hours=2)
        jobs.jobs["stuck"] = build_job(id="stuck", status=JobStatus.RUNNING, updated_at=stale)
        use_case, _ = build_submit(jobs=jobs)
        job = use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertEqual(job.status, JobStatus.QUEUED)  # new job created
        self.assertIn("stuck", [job_id for job_id, _ in jobs.failed_with])  # old one retired

    def test_service_failure_marks_job_failed_and_reports_502(self) -> None:
        """A QUEUED row left behind would block this video forever."""

        jobs = FakeJobRepository()
        use_case, _ = build_submit(jobs=jobs, processing=FakeProcessingService(fail=True))

        with self.assertRaises(JobError) as ctx:
            use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))

        self.assertEqual(ctx.exception.code, PROCESSING_SERVICE_UNAVAILABLE)
        self.assertEqual(len(jobs.failed_with), 1)
        self.assertEqual(jobs.jobs[JOB_ID].status, JobStatus.FAILED)

    def test_team_access_is_checked_before_any_write(self) -> None:
        jobs = FakeJobRepository()
        use_case, _ = build_submit(jobs=jobs, team_access=FakeTeamAccess(allowed=False))
        with self.assertRaises(JobError):
            use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertEqual(jobs.jobs, {})

    def test_never_blocks_on_the_gpu(self) -> None:
        """The service call returns an id immediately; nothing here waits."""

        service = FakeProcessingService()
        use_case, _ = build_submit(processing=service)
        use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertEqual(len(service.calls), 1)


class TestRecordJobProgress(unittest.TestCase):
    """Status callbacks from the processing service."""

    def build(self, initial: JobStatus = JobStatus.QUEUED):
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job(status=initial)
        return RecordJobProgressUseCase(jobs=jobs, uow=FakeUnitOfWork()), jobs

    def test_running_marks_job_running(self) -> None:
        use_case, _ = self.build()
        job = use_case.execute(
            RecordJobProgressCommand(job_id=JOB_ID, status=JobStatus.RUNNING, progress_percent=20)
        )
        self.assertEqual(job.status, JobStatus.RUNNING)
        self.assertEqual(job.progress_percent, 20)

    def test_done_records_results_key(self) -> None:
        use_case, _ = self.build(JobStatus.RUNNING)
        job = use_case.execute(
            RecordJobProgressCommand(job_id=JOB_ID, status=JobStatus.DONE, results_key="results/t/j")
        )
        self.assertEqual(job.status, JobStatus.DONE)
        self.assertEqual(job.results_key, "results/t/j")

    def test_failed_records_error_message(self) -> None:
        use_case, jobs = self.build(JobStatus.RUNNING)
        job = use_case.execute(
            RecordJobProgressCommand(job_id=JOB_ID, status=JobStatus.FAILED, error_message="OOM")
        )
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(jobs.failed_with[0][1], "OOM")

    def test_failed_without_message_still_records_something(self) -> None:
        use_case, jobs = self.build(JobStatus.RUNNING)
        use_case.execute(RecordJobProgressCommand(job_id=JOB_ID, status=JobStatus.FAILED))
        self.assertTrue(jobs.failed_with[0][1])

    def test_callback_for_finished_job_is_ignored(self) -> None:
        """Retried or out-of-order callbacks must not resurrect a finished job."""

        use_case, _ = self.build(JobStatus.DONE)
        job = use_case.execute(RecordJobProgressCommand(job_id=JOB_ID, status=JobStatus.RUNNING))
        self.assertEqual(job.status, JobStatus.DONE)

    def test_failed_job_is_not_overwritten_by_a_late_success(self) -> None:
        use_case, _ = self.build(JobStatus.FAILED)
        job = use_case.execute(RecordJobProgressCommand(job_id=JOB_ID, status=JobStatus.DONE))
        self.assertEqual(job.status, JobStatus.FAILED)

    def test_duplicate_running_callbacks_are_safe(self) -> None:
        use_case, _ = self.build()
        use_case.execute(RecordJobProgressCommand(job_id=JOB_ID, status=JobStatus.RUNNING))
        job = use_case.execute(RecordJobProgressCommand(job_id=JOB_ID, status=JobStatus.RUNNING))
        self.assertEqual(job.status, JobStatus.RUNNING)

    def test_unknown_job_is_not_found(self) -> None:
        use_case = RecordJobProgressUseCase(jobs=FakeJobRepository(), uow=FakeUnitOfWork())
        with self.assertRaises(JobError) as ctx:
            use_case.execute(RecordJobProgressCommand(job_id="missing", status=JobStatus.DONE))
        self.assertEqual(ctx.exception.code, JOB_NOT_FOUND)

    def test_queued_cannot_be_reported_by_the_service(self) -> None:
        use_case, _ = self.build()
        with self.assertRaises(JobError) as ctx:
            use_case.execute(RecordJobProgressCommand(job_id=JOB_ID, status=JobStatus.QUEUED))
        self.assertEqual(ctx.exception.code, INVALID_JOB_STATUS)


class FakeUrlSigner:
    """Signing is local, so a fake needs no storage and makes no network call."""

    def __init__(self) -> None:
        self.signed: list[str] = []

    def presign(self, *, key, expires_in):
        self.signed.append(key)
        return f"https://storage.example/{key}?expires={expires_in}"


class TestGetJobResults(unittest.TestCase):
    def build(self, job):
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = job
        signer = FakeUrlSigner()
        return (
            GetJobResultsUseCase(jobs=jobs, urls=signer, team_access=FakeTeamAccess()),
            signer,
        )

    def finished_job(self, **overrides):
        fields = {
            "results_key": f"results/{TEAM_ID}/{JOB_ID}",
            "artifacts": ["results.json", "projected_shots.json", "tracks.jsonl"],
            "summary": {"frames_processed": 146, "distinct_track_ids": 10},
        }
        fields.update(overrides)
        return build_job(status=JobStatus.DONE, **fields)

    def test_presigns_every_reported_artifact(self) -> None:
        use_case, signer = self.build(self.finished_job())
        payload = use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)

        self.assertEqual(
            sorted(payload["artifact_urls"]),
            ["projected_shots.json", "results.json", "tracks.jsonl"],
        )
        self.assertTrue(
            all(k.startswith(f"results/{TEAM_ID}/{JOB_ID}/") for k in signer.signed)
        )

    def test_summary_is_returned_inline(self) -> None:
        """The UI shows outcome numbers without a second request."""

        use_case, _ = self.build(self.finished_job())
        payload = use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(payload["summary"]["distinct_track_ids"], 10)

    def test_nothing_is_read_from_storage(self) -> None:
        """Only signing happens here — a signer with no read method must suffice."""

        use_case, signer = self.build(self.finished_job())
        use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertFalse(hasattr(signer, "read_results"))
        self.assertEqual(len(signer.signed), 3)

    def test_unfinished_job_is_conflict_not_empty_results(self) -> None:
        use_case, _ = self.build(build_job(status=JobStatus.RUNNING))
        with self.assertRaises(JobError) as ctx:
            use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(ctx.exception.code, JOB_NOT_FINISHED)

    def test_done_job_without_artifacts_returns_empty_urls(self) -> None:
        """A job that reported no artifacts is valid, just empty."""

        use_case, _ = self.build(self.finished_job(artifacts=None))
        payload = use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(payload["artifact_urls"], {})

    def test_missing_results_key_is_reported(self) -> None:
        job = build_job(status=JobStatus.DONE, results_key=None, artifacts=["results.json"])
        use_case, _ = self.build(job)
        with self.assertRaises(JobError) as ctx:
            use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(ctx.exception.code, RESULTS_NOT_AVAILABLE)

    def test_unknown_job_is_not_found(self) -> None:
        use_case = GetJobResultsUseCase(
            jobs=FakeJobRepository(), urls=FakeUrlSigner(), team_access=FakeTeamAccess()
        )
        with self.assertRaises(JobError) as ctx:
            use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id="missing")
        self.assertEqual(ctx.exception.code, JOB_NOT_FOUND)


class TestPipelineSelection(unittest.TestCase):
    def test_pipeline_is_forwarded_to_the_service(self) -> None:
        use_case, parts = build_submit()
        use_case.execute(
            SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID, pipeline="player-positions")
        )
        self.assertEqual(parts["processing"].calls[0]["pipeline"], "player-positions")

    def test_pipeline_defaults_to_none_so_the_service_chooses(self) -> None:
        use_case, parts = build_submit()
        use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertIsNone(parts["processing"].calls[0]["pipeline"])


class TestGetProcessingJob(unittest.TestCase):
    def test_returns_job(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job()
        use_case = GetProcessingJobUseCase(jobs=jobs, team_access=FakeTeamAccess())
        self.assertEqual(use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID).id, JOB_ID)

    def test_unknown_job_is_not_found(self) -> None:
        use_case = GetProcessingJobUseCase(jobs=FakeJobRepository(), team_access=FakeTeamAccess())
        with self.assertRaises(JobError) as ctx:
            use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id="missing")
        self.assertEqual(ctx.exception.code, JOB_NOT_FOUND)


class TestListVideoJobs(unittest.TestCase):
    def test_lists_jobs_for_one_video(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job()
        use_case = ListVideoJobsUseCase(jobs=jobs, team_access=FakeTeamAccess())
        result = use_case.execute(user_id=USER_ID, team_id=TEAM_ID, video_id=VIDEO_ID)
        self.assertEqual([j.id for j in result], [JOB_ID])

    def test_empty_when_video_has_no_jobs(self) -> None:
        use_case = ListVideoJobsUseCase(jobs=FakeJobRepository(), team_access=FakeTeamAccess())
        self.assertEqual(use_case.execute(user_id=USER_ID, team_id=TEAM_ID, video_id=VIDEO_ID), [])


def ago(delta: timedelta) -> datetime:
    return datetime.now(timezone.utc) - delta


class TestHeartbeatStaleness(unittest.TestCase):
    def test_heartbeat_window_is_fifteen_minutes(self) -> None:
        self.assertEqual(STALE_ACTIVE_JOB_HEARTBEAT, timedelta(minutes=15))

    def test_submit_keeps_a_job_that_reported_14m59s_ago(self) -> None:
        use_case, parts = build_submit()
        parts["jobs"].jobs["live"] = build_job(
            id="live", status=JobStatus.RUNNING, updated_at=ago(timedelta(minutes=14, seconds=59))
        )
        job = use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertEqual(job.id, "live")
        self.assertEqual(parts["jobs"].failed_with, [])

    def test_submit_retires_a_job_that_reported_15m01s_ago(self) -> None:
        use_case, parts = build_submit()
        parts["jobs"].jobs["dead"] = build_job(
            id="dead", status=JobStatus.RUNNING, updated_at=ago(timedelta(minutes=15, seconds=1))
        )
        job = use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertEqual(job.id, JOB_ID)
        self.assertEqual(parts["jobs"].failed_with, [("dead", STALE_JOB_ERROR_MESSAGE)])

    def test_a_queued_job_is_subject_to_the_same_rule(self) -> None:
        job = build_job(status=JobStatus.QUEUED, updated_at=ago(timedelta(minutes=16)))
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = job
        use_case = GetProcessingJobUseCase(jobs=jobs, team_access=FakeTeamAccess())
        self.assertEqual(use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID).status, JobStatus.FAILED)

    def test_backstop_retires_a_job_that_keeps_heartbeating_past_75_minutes(self) -> None:
        self.assertEqual(STALE_ACTIVE_JOB_MAX_RUNTIME, timedelta(minutes=75))
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job(
            status=JobStatus.RUNNING,
            started_at=ago(timedelta(minutes=75, seconds=1)),
            updated_at=ago(timedelta(seconds=5)),
        )
        use_case = GetProcessingJobUseCase(jobs=jobs, team_access=FakeTeamAccess())
        self.assertEqual(use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID).status, JobStatus.FAILED)

    def test_backstop_does_not_fire_at_74_minutes(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job(
            status=JobStatus.RUNNING,
            started_at=ago(timedelta(minutes=74)),
            updated_at=ago(timedelta(seconds=5)),
        )
        use_case = GetProcessingJobUseCase(jobs=jobs, team_access=FakeTeamAccess())
        self.assertEqual(use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID).status, JobStatus.RUNNING)

    def test_backstop_uses_created_at_when_the_job_never_started(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job(
            status=JobStatus.QUEUED,
            created_at=ago(timedelta(minutes=76)),
            updated_at=ago(timedelta(seconds=5)),
        )
        use_case = GetProcessingJobUseCase(jobs=jobs, team_access=FakeTeamAccess())
        self.assertEqual(use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID).status, JobStatus.FAILED)

    def test_get_retires_a_stale_job_with_the_stale_message(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job(status=JobStatus.RUNNING, updated_at=ago(timedelta(minutes=20)))
        uow = FakeUnitOfWork()
        use_case = GetProcessingJobUseCase(jobs=jobs, team_access=FakeTeamAccess(), uow=uow)
        job = use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.error_message, STALE_JOB_ERROR_MESSAGE)
        self.assertEqual(uow.transactions, 1)

    def test_get_is_idempotent_and_never_touches_terminal_jobs(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job(status=JobStatus.RUNNING, updated_at=ago(timedelta(minutes=20)))
        jobs.jobs["done"] = build_job(id="done", status=JobStatus.DONE, updated_at=ago(timedelta(hours=5)))
        use_case = GetProcessingJobUseCase(jobs=jobs, team_access=FakeTeamAccess())
        use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID)
        done = use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id="done")
        self.assertEqual(done.status, JobStatus.DONE)
        self.assertEqual(jobs.failed_with, [(JOB_ID, STALE_JOB_ERROR_MESSAGE)])

    def test_get_leaves_a_fresh_job_alone(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job(status=JobStatus.RUNNING, updated_at=ago(timedelta(minutes=14, seconds=59)))
        use_case = GetProcessingJobUseCase(jobs=jobs, team_access=FakeTeamAccess())
        self.assertEqual(use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID).status, JobStatus.RUNNING)
        self.assertEqual(jobs.failed_with, [])

    def test_list_retires_only_the_stale_active_jobs(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs["stale"] = build_job(id="stale", status=JobStatus.RUNNING, updated_at=ago(timedelta(minutes=30)))
        jobs.jobs["fresh"] = build_job(id="fresh", status=JobStatus.RUNNING, updated_at=ago(timedelta(minutes=1)))
        jobs.jobs["done"] = build_job(id="done", status=JobStatus.DONE, updated_at=ago(timedelta(days=1)))
        use_case = ListVideoJobsUseCase(jobs=jobs, team_access=FakeTeamAccess())
        statuses = {j.id: j.status for j in use_case.execute(user_id=USER_ID, team_id=TEAM_ID, video_id=VIDEO_ID)}
        self.assertEqual(
            statuses,
            {"stale": JobStatus.FAILED, "fresh": JobStatus.RUNNING, "done": JobStatus.DONE},
        )
        self.assertEqual(jobs.failed_with, [("stale", STALE_JOB_ERROR_MESSAGE)])


class TestProgressPhase(unittest.TestCase):
    def _record(self, jobs, **kwargs):
        use_case = RecordJobProgressUseCase(jobs=jobs, uow=FakeUnitOfWork())
        return use_case.execute(RecordJobProgressCommand(job_id=JOB_ID, status=JobStatus.RUNNING, **kwargs))

    def test_phase_round_trips_through_a_running_report(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job()
        job = self._record(jobs, progress_percent=10, progress_phase="tracking")
        self.assertEqual(job.progress_phase, "tracking")
        self.assertEqual(jobs.jobs[JOB_ID].progress_phase, "tracking")

    def test_old_payload_without_a_phase_still_works(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job()
        job = self._record(jobs, progress_percent=30)
        self.assertEqual(job.progress_percent, 30)
        self.assertIsNone(job.progress_phase)

    def test_a_report_without_a_phase_keeps_the_previous_one(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job()
        self._record(jobs, progress_percent=10, progress_phase="tracking")
        job = self._record(jobs, progress_percent=12)
        self.assertEqual(job.progress_phase, "tracking")

    def test_progress_never_goes_backwards(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job()
        self._record(jobs, progress_percent=40)
        job = self._record(jobs, progress_percent=25)
        self.assertEqual(job.progress_percent, 40)

    def test_callback_after_a_terminal_status_is_ignored(self) -> None:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job(status=JobStatus.FAILED, error_message="boom")
        job = self._record(jobs, progress_percent=50, progress_phase="tracking")
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertIsNone(job.progress_phase)

    def test_router_payload_trims_and_bounds_the_phase(self) -> None:
        from pydantic import ValidationError

        from src.interfaces.http.routes.jobs_router import JobStatusCallbackPayload

        base = {"job_id": JOB_ID, "status": "RUNNING"}
        self.assertIsNone(JobStatusCallbackPayload(**base).progress_phase)
        self.assertEqual(JobStatusCallbackPayload(**base, progress_phase="  tracking ").progress_phase, "tracking")
        self.assertIsNone(JobStatusCallbackPayload(**base, progress_phase="   ").progress_phase)
        with self.assertRaises(ValidationError):
            JobStatusCallbackPayload(**base, progress_phase="x" * 41)

    def test_job_dict_includes_the_phase(self) -> None:
        from src.interfaces.http.routes.jobs_router import _job_to_dict

        self.assertEqual(_job_to_dict(build_job(progress_phase="identity"))["progress_phase"], "identity")
        self.assertIsNone(_job_to_dict(build_job())["progress_phase"])


class TestSetJobTeamSide(unittest.TestCase):
    def _jobs(self) -> FakeJobRepository:
        jobs = FakeJobRepository()
        jobs.jobs[JOB_ID] = build_job(JobStatus.DONE)
        return jobs

    def test_execute_keeps_returning_the_job_and_runs_the_hook(self) -> None:
        seen = []
        use_case = SetJobTeamSideUseCase(
            jobs=self._jobs(), team_access=FakeTeamAccess(), on_changed=lambda job: seen.append(job.id) or "ok"
        )
        job = use_case.execute(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID, our_team_side=1)
        self.assertEqual((job.our_team_side, seen), (1, [JOB_ID]))

    def test_execute_and_sync_also_returns_what_the_hook_reported(self) -> None:
        use_case = SetJobTeamSideUseCase(
            jobs=self._jobs(), team_access=FakeTeamAccess(), on_changed=lambda job: "not_latest"
        )
        job, status = use_case.execute_and_sync(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID, our_team_side=0)
        self.assertEqual((job.our_team_side, status), (0, "not_latest"))

    def test_without_a_hook_the_status_is_none(self) -> None:
        use_case = SetJobTeamSideUseCase(jobs=self._jobs(), team_access=FakeTeamAccess())
        self.assertIsNone(use_case.execute_and_sync(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID, our_team_side=1)[1])

    def test_an_unknown_job_is_not_found_and_runs_no_hook(self) -> None:
        seen = []
        use_case = SetJobTeamSideUseCase(jobs=FakeJobRepository(), team_access=FakeTeamAccess(), on_changed=seen.append)
        with self.assertRaises(JobError) as caught:
            use_case.execute_and_sync(user_id=USER_ID, team_id=TEAM_ID, job_id=JOB_ID, our_team_side=1)
        self.assertEqual((caught.exception.code, seen), (JOB_NOT_FOUND, []))


class TestJobStatus(unittest.TestCase):
    def test_terminal_and_active_are_complementary(self) -> None:
        for status in JobStatus:
            self.assertNotEqual(status.is_terminal, status.is_active)

    def test_done_and_failed_are_terminal(self) -> None:
        self.assertTrue(JobStatus.DONE.is_terminal)
        self.assertTrue(JobStatus.FAILED.is_terminal)
        self.assertTrue(JobStatus.QUEUED.is_active)
        self.assertTrue(JobStatus.RUNNING.is_active)


if __name__ == "__main__":
    unittest.main()
