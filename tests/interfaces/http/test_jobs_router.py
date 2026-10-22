from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.jobs.errors import (
    JOB_ALREADY_ACTIVE,
    JOB_NOT_FOUND,
    PROCESSING_SERVICE_UNAVAILABLE,
    VIDEO_NOT_READY,
    JobError,
)
from src.domain.jobs.entities import JobStatus, ProcessingJob
from src.interfaces.http.routes.jobs_router import create_jobs_router

TEAM_ID = "11111111-1111-1111-1111-111111111111"
VIDEO_ID = "22222222-2222-2222-2222-222222222222"
JOB_ID = "33333333-3333-3333-3333-333333333333"


def build_job(status: JobStatus = JobStatus.QUEUED, **overrides) -> ProcessingJob:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    defaults = {
        "id": JOB_ID,
        "video_id": VIDEO_ID,
        "team_id": TEAM_ID,
        "requested_by_user_id": "user-1",
        "status": status,
        "external_job_id": "ext-1",
        "results_key": None,
        "error_message": None,
        "progress_percent": None,
        "started_at": None,
        "finished_at": None,
        "created_at": now,
        "updated_at": now,
    }
    return ProcessingJob(**{**defaults, **overrides})


class _Ok:
    def __init__(self, value):
        self.value = value

    def execute(self, *_args, **_kwargs):
        return self.value


class _Raises:
    def __init__(self, code):
        self.code = code

    def execute(self, *_args, **_kwargs):
        raise JobError(code=self.code, message=f"failed: {self.code}")


CALLBACK_TOKEN = "callback-token-abc"


class _Records:
    """Captures what the callback use case was asked to do."""

    def __init__(self, value=None):
        self.value = value or build_job(JobStatus.DONE)
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        return self.value


def build_client(
    *,
    submit=None,
    get=None,
    listing=None,
    record=None,
    results=None,
    set_team_side=None,
    callback_token=CALLBACK_TOKEN,
) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request, call_next):
        request.state.user_id = "user-1"
        return await call_next(request)

    app.include_router(
        create_jobs_router(
            submit_job_use_case=submit or _Ok(build_job()),
            get_job_use_case=get or _Ok(build_job()),
            list_video_jobs_use_case=listing or _Ok([build_job()]),
            record_job_progress_use_case=record or _Records(),
            get_job_results_use_case=results or _Ok({"job_id": JOB_ID, "artifact_urls": {}}),
            set_team_side_use_case=set_team_side or _Ok(build_job()),
            callback_token=callback_token,
        )
    )
    return TestClient(app)


class TestSubmitJobEndpoint(unittest.TestCase):
    def test_returns_202_accepted_not_200(self) -> None:
        """202 signals the work was queued, not completed."""

        client = build_client()
        response = client.post(f"/videos/{VIDEO_ID}/jobs", json={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["job"]["id"], JOB_ID)
        self.assertEqual(response.json()["job"]["status"], "QUEUED")

    def test_does_not_leak_internal_job_identifier(self) -> None:
        """The provider's call id is an implementation detail of the service."""

        client = build_client()
        body = client.post(f"/videos/{VIDEO_ID}/jobs", json={"team_id": TEAM_ID}).json()
        self.assertNotIn("external_job_id", body["job"])

    def test_duplicate_submission_is_conflict(self) -> None:
        client = build_client(submit=_Raises(JOB_ALREADY_ACTIVE))
        response = client.post(f"/videos/{VIDEO_ID}/jobs", json={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], JOB_ALREADY_ACTIVE)

    def test_video_not_ready_is_conflict(self) -> None:
        client = build_client(submit=_Raises(VIDEO_NOT_READY))
        response = client.post(f"/videos/{VIDEO_ID}/jobs", json={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 409)

    def test_service_unavailable_is_bad_gateway(self) -> None:
        """The processing service is a third party from this app's perspective."""

        client = build_client(submit=_Raises(PROCESSING_SERVICE_UNAVAILABLE))
        response = client.post(f"/videos/{VIDEO_ID}/jobs", json={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 502)

    def test_missing_team_id_is_rejected(self) -> None:
        client = build_client()
        self.assertEqual(client.post(f"/videos/{VIDEO_ID}/jobs", json={}).status_code, 422)

    def test_non_uuid_video_id_is_rejected(self) -> None:
        client = build_client()
        response = client.post("/videos/not-a-uuid/jobs", json={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 422)


class TestGetJobEndpoint(unittest.TestCase):
    def test_returns_job_status(self) -> None:
        client = build_client(get=_Ok(build_job(JobStatus.DONE, results_key="results/t/j")))
        body = client.get(f"/jobs/{JOB_ID}", params={"team_id": TEAM_ID}).json()
        self.assertEqual(body["job"]["status"], "DONE")
        self.assertEqual(body["job"]["results_key"], "results/t/j")

    def test_unknown_job_is_404(self) -> None:
        client = build_client(get=_Raises(JOB_NOT_FOUND))
        response = client.get(f"/jobs/{JOB_ID}", params={"team_id": TEAM_ID})
        self.assertEqual(response.status_code, 404)

    def test_team_id_is_required(self) -> None:
        client = build_client()
        self.assertEqual(client.get(f"/jobs/{JOB_ID}").status_code, 422)

    def test_failed_job_exposes_error_message(self) -> None:
        client = build_client(get=_Ok(build_job(JobStatus.FAILED, error_message="boom")))
        body = client.get(f"/jobs/{JOB_ID}", params={"team_id": TEAM_ID}).json()
        self.assertEqual(body["job"]["error_message"], "boom")


class TestListVideoJobsEndpoint(unittest.TestCase):
    def test_lists_jobs(self) -> None:
        client = build_client()
        body = client.get(f"/videos/{VIDEO_ID}/jobs", params={"team_id": TEAM_ID}).json()
        self.assertEqual(len(body["jobs"]), 1)

    def test_empty_list_is_valid(self) -> None:
        client = build_client(listing=_Ok([]))
        body = client.get(f"/videos/{VIDEO_ID}/jobs", params={"team_id": TEAM_ID}).json()
        self.assertEqual(body["jobs"], [])


class TestStatusCallbackEndpoint(unittest.TestCase):
    """The callback is exempt from user auth, so its token check is the only guard."""

    URL = "/internal/jobs/status"
    BODY = {"job_id": JOB_ID, "status": "DONE", "results_key": "results/t/j"}

    def post(self, client, *, token=CALLBACK_TOKEN, body=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return client.post(self.URL, json=body or self.BODY, headers=headers)

    def test_valid_token_is_accepted(self) -> None:
        record = _Records()
        response = self.post(build_client(record=record))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(record.commands[0].job_id, JOB_ID)
        self.assertEqual(record.commands[0].status, JobStatus.DONE)

    def test_missing_token_is_rejected(self) -> None:
        record = _Records()
        response = self.post(build_client(record=record), token=None)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(record.commands, [], "must not reach the use case")

    def test_wrong_token_is_rejected(self) -> None:
        record = _Records()
        response = self.post(build_client(record=record), token="not-the-token")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(record.commands, [])

    def test_unconfigured_token_fails_closed(self) -> None:
        """An empty configured token must reject everything, not accept everything."""

        record = _Records()
        client = build_client(record=record, callback_token="")
        self.assertEqual(self.post(client, token="").status_code, 401)
        self.assertEqual(self.post(client, token="anything").status_code, 401)
        self.assertEqual(record.commands, [])

    def test_results_key_and_error_are_forwarded(self) -> None:
        record = _Records()
        self.post(
            build_client(record=record),
            body={"job_id": JOB_ID, "status": "FAILED", "error_message": "CUDA OOM"},
        )
        self.assertEqual(record.commands[0].error_message, "CUDA OOM")

    def test_queued_is_not_an_accepted_callback_status(self) -> None:
        """Only the service's own lifecycle states may be reported."""

        response = self.post(
            build_client(), body={"job_id": JOB_ID, "status": "QUEUED"}
        )
        self.assertEqual(response.status_code, 422)

    def test_unknown_job_is_404(self) -> None:
        response = self.post(build_client(record=_Raises(JOB_NOT_FOUND)))
        self.assertEqual(response.status_code, 404)

    def test_non_uuid_job_id_is_rejected(self) -> None:
        response = self.post(build_client(), body={"job_id": "nope", "status": "DONE"})
        self.assertEqual(response.status_code, 422)


class TestCallbackPathIsExemptFromUserAuth(unittest.TestCase):
    def test_callback_path_is_listed_in_public_routes(self) -> None:
        """If this drifts, every callback 401s at the middleware before its token check."""

        from src.interfaces.http.middleware.auth_middleware import PUBLIC_ROUTES
        from src.interfaces.http.routes.jobs_router import CALLBACK_PATH

        self.assertIn(CALLBACK_PATH, PUBLIC_ROUTES)


if __name__ == "__main__":
    unittest.main()


class _SetsSide:
    def __init__(self, sync_status):
        self.sync_status = sync_status
        self.calls = []

    def execute_and_sync(self, **kwargs):
        self.calls.append(kwargs)
        return build_job(our_team_side=kwargs["our_team_side"]), self.sync_status


class TestSetOurTeamEndpoint(unittest.TestCase):
    def test_the_response_reports_what_happened_to_the_player_stats(self) -> None:
        setter = _SetsSide("not_latest")
        client = build_client(set_team_side=setter)
        response = client.put(f"/jobs/{JOB_ID}/our-team?team_id={TEAM_ID}", json={"team_side": 1})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["player_stats_sync"], "not_latest")
        self.assertEqual(body["job"]["our_team_side"], 1)
        self.assertEqual(setter.calls[0]["our_team_side"], 1)

    def test_it_is_null_when_no_sync_is_wired(self) -> None:
        client = build_client(set_team_side=_SetsSide(None))
        response = client.put(f"/jobs/{JOB_ID}/our-team?team_id={TEAM_ID}", json={"team_side": 0})
        self.assertIsNone(response.json()["player_stats_sync"])

    def test_a_missing_job_keeps_the_error_envelope(self) -> None:
        class _Missing:
            def execute_and_sync(self, **_):
                raise JobError(code=JOB_NOT_FOUND, message="Job not found.")

        response = build_client(set_team_side=_Missing()).put(
            f"/jobs/{JOB_ID}/our-team?team_id={TEAM_ID}", json={"team_side": 0}
        )
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (404, JOB_NOT_FOUND))
