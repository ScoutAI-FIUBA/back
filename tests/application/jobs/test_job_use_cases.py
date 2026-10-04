from __future__ import annotations

import unittest
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
    SubmitProcessingJobCommand,
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
        self.failed_with.append((job_id, error_message))
        job = build_job(id=job_id, status=JobStatus.FAILED, error_message=error_message)
        self.jobs[job_id] = job
        return job

    def get_by_id(self, *, job_id, team_id):
        return self.jobs.get(job_id)

    def get_by_id_unscoped(self, *, job_id):
        return self.jobs.get(job_id)

    def mark_running(self, *, job_id, progress_percent):
        job = build_job(id=job_id, status=JobStatus.RUNNING, progress_percent=progress_percent)
        self.jobs[job_id] = job
        return job

    def mark_done(self, *, job_id, results_key, artifacts=None, summary=None):
        job = build_job(id=job_id, status=JobStatus.DONE, results_key=results_key,
                        progress_percent=100, artifacts=artifacts, summary=summary)
        self.jobs[job_id] = job
        return job

    def list_by_video(self, *, video_id, team_id):
        return [j for j in self.jobs.values() if j.video_id == video_id]

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

    def test_second_job_for_same_video_is_rejected(self) -> None:
        """GPU minutes are the expensive resource; double submits must not spend twice."""

        use_case, _ = build_submit(jobs=FakeJobRepository(raise_active=True))
        with self.assertRaises(JobError) as ctx:
            use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertEqual(ctx.exception.code, JOB_ALREADY_ACTIVE)

    def test_a_live_active_job_is_not_retired(self) -> None:
        """A recent running job is real work in flight — leave it, reject the dupe."""

        jobs = FakeJobRepository(raise_active=True)
        jobs.jobs["old"] = build_job(
            id="old", status=JobStatus.RUNNING, updated_at=datetime.now(timezone.utc)
        )
        use_case, _ = build_submit(jobs=jobs)
        with self.assertRaises(JobError) as ctx:
            use_case.execute(SubmitProcessingJobCommand(USER_ID, TEAM_ID, VIDEO_ID))
        self.assertEqual(ctx.exception.code, JOB_ALREADY_ACTIVE)
        self.assertEqual(jobs.failed_with, [])  # the live job was not touched

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
