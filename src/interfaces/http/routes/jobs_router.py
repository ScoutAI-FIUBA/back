from __future__ import annotations

import hmac
from http import HTTPStatus
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.application.jobs.errors import JobError, job_error_http_status
from src.application.jobs.use_cases import (
    GetJobResultsUseCase,
    GetProcessingJobUseCase,
    ListVideoJobsUseCase,
    RecordJobProgressCommand,
    RecordJobProgressUseCase,
    SubmitProcessingJobCommand,
    SubmitProcessingJobUseCase,
)
from src.domain.jobs.entities import JobStatus


# Fixed path so the auth middleware, which matches exact paths, can exempt it
# from user authentication. The job id travels in the body instead.
CALLBACK_PATH = "/internal/jobs/status"


class SubmitJobPayload(BaseModel):
    team_id: UUID
    # Which pipeline to run. None lets the processing service pick its default.
    pipeline: str | None = None


class JobStatusCallbackPayload(BaseModel):
    job_id: UUID
    status: Literal["RUNNING", "DONE", "FAILED"]
    results_key: str | None = None
    error_message: str | None = None
    progress_percent: int | None = None
    artifacts: list[str] | None = None
    summary: dict | None = None


def _job_to_dict(job) -> dict[str, object]:
    return {
        "id": job.id,
        "video_id": job.video_id,
        "team_id": job.team_id,
        "requested_by_user_id": job.requested_by_user_id,
        "status": job.status.value,
        "results_key": job.results_key,
        "error_message": job.error_message,
        "progress_percent": job.progress_percent,
        "summary": job.summary,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def create_jobs_router(
    *,
    submit_job_use_case: SubmitProcessingJobUseCase,
    get_job_use_case: GetProcessingJobUseCase,
    list_video_jobs_use_case: ListVideoJobsUseCase,
    record_job_progress_use_case: RecordJobProgressUseCase,
    get_job_results_use_case: GetJobResultsUseCase,
    callback_token: str,
) -> APIRouter:
    router = APIRouter(tags=["jobs"])

    @router.post(CALLBACK_PATH, response_model=None)
    def record_job_status(payload: JobStatusCallbackPayload, authorization: str = Header(default="")):
        """Status callback from the processing service.

        This path is exempt from user authentication in the auth middleware,
        because the caller is a machine with no user session. It is therefore
        NOT public: the shared-token check below is the only thing standing
        between the internet and arbitrary job-status writes, and must run before
        anything else.
        """

        supplied = authorization.removeprefix("Bearer ").strip()
        # Rejects when no token is configured: an unset token must fail closed,
        # never accept everything.
        if not callback_token or not supplied or not hmac.compare_digest(supplied, callback_token):
            return JSONResponse(
                status_code=HTTPStatus.UNAUTHORIZED,
                content={"error": {"code": "UNAUTHORIZED", "message": "Invalid callback token."}},
            )

        try:
            job = record_job_progress_use_case.execute(
                RecordJobProgressCommand(
                    job_id=str(payload.job_id),
                    status=JobStatus(payload.status),
                    results_key=payload.results_key,
                    error_message=payload.error_message,
                    progress_percent=payload.progress_percent,
                    artifacts=payload.artifacts,
                    summary=payload.summary,
                )
            )
            return {"job": _job_to_dict(job)}
        except JobError as exc:
            return JSONResponse(status_code=job_error_http_status(exc.code), content=exc.to_envelope())

    @router.post("/videos/{video_id}/jobs", status_code=HTTPStatus.ACCEPTED, response_model=None)
    def submit_job(video_id: UUID, payload: SubmitJobPayload, request: Request):
        """Queue a video for processing.

        Returns 202 immediately with a job id. Processing takes minutes to hours,
        so the client polls `GET /jobs/{job_id}` rather than waiting here.
        """

        try:
            job = submit_job_use_case.execute(
                SubmitProcessingJobCommand(
                    user_id=str(request.state.user_id),
                    team_id=str(payload.team_id),
                    video_id=str(video_id),
                    pipeline=payload.pipeline,
                )
            )
            return {"job": _job_to_dict(job)}
        except JobError as exc:
            return JSONResponse(status_code=job_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/videos/{video_id}/jobs", response_model=None)
    def list_video_jobs(video_id: UUID, team_id: UUID, request: Request):
        try:
            jobs = list_video_jobs_use_case.execute(
                user_id=str(request.state.user_id),
                team_id=str(team_id),
                video_id=str(video_id),
            )
            return {"jobs": [_job_to_dict(job) for job in jobs]}
        except JobError as exc:
            return JSONResponse(status_code=job_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/jobs/{job_id}/results", response_model=None)
    def get_job_results(job_id: UUID, team_id: UUID, request: Request):
        """Analysis output for a finished job.

        Returns the summary inline plus short-lived download URLs for each
        artifact, so the browser fetches large files straight from storage.
        """

        try:
            return get_job_results_use_case.execute(
                user_id=str(request.state.user_id),
                team_id=str(team_id),
                job_id=str(job_id),
            )
        except JobError as exc:
            return JSONResponse(status_code=job_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/jobs/{job_id}", response_model=None)
    def get_job(job_id: UUID, team_id: UUID, request: Request):
        """Poll one job's status. This is the endpoint the browser polls."""

        try:
            job = get_job_use_case.execute(
                user_id=str(request.state.user_id),
                team_id=str(team_id),
                job_id=str(job_id),
            )
            return {"job": _job_to_dict(job)}
        except JobError as exc:
            return JSONResponse(status_code=job_error_http_status(exc.code), content=exc.to_envelope())

    return router
