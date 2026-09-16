"""HTTP adapter for the GPU processing service.

Speaks to whatever is listening on `PROCESSING_SERVICE_URL` — currently a Modal
endpoint, but nothing here knows or cares. Keeping the vendor out of the name and
the code means swapping providers is one adapter, not a refactor.

This adapter never waits for processing to finish. It POSTs a job and expects an
acknowledgement within seconds; the actual work takes minutes to hours and its
result arrives by the service updating the database directly.
"""

from __future__ import annotations

import httpx

from src.application.jobs.ports import ProcessingServiceError, SubmittedJob

# The submit call should return almost immediately — it only enqueues work. A
# short timeout means a hanging service surfaces as a clean 502 to our caller
# rather than tying up a web worker.
DEFAULT_TIMEOUT_SECONDS = 15.0


class HttpProcessingService:
    def __init__(
        self,
        *,
        endpoint_url: str,
        auth_token: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._endpoint_url = endpoint_url.rstrip("/")
        self._auth_token = auth_token
        self._timeout = timeout_seconds

    def submit(
        self,
        *,
        job_id: str,
        video_storage_key: str,
        results_key: str,
        pipeline: str | None = None,
    ) -> SubmittedJob:
        payload: dict[str, object] = {
            # Echoed back by the service on its status callbacks, which is the
            # only way we can tell which job a callback refers to.
            "job_id": job_id,
            "r2_key": video_storage_key,
            "output_prefix": results_key,
        }
        if pipeline:
            payload["pipeline"] = pipeline
        try:
            response = httpx.post(
                self._endpoint_url,
                json=payload,
                # The token is what stops anyone on the internet from spending
                # our GPU budget. It is never logged.
                headers={"Authorization": f"Bearer {self._auth_token}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProcessingServiceError(f"Could not reach processing service: {exc}") from exc

        if response.status_code >= 400:
            raise ProcessingServiceError(
                f"Processing service returned {response.status_code}: {response.text[:200]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ProcessingServiceError("Processing service returned a non-JSON response") from exc

        external_id = body.get("call_id") or body.get("job_id")
        if not external_id:
            raise ProcessingServiceError(
                "Processing service response did not include a job identifier"
            )
        return SubmittedJob(external_job_id=str(external_id))


class UnconfiguredProcessingService:
    """Stand-in used when no processing service is configured.

    Lets the rest of the app boot and every other endpoint work while the GPU
    service does not exist yet. Submitting a job fails cleanly with a 502 and an
    explanation, instead of the app refusing to start or raising a confusing
    connection error.
    """

    def submit(
        self,
        *,
        job_id: str,
        video_storage_key: str,
        results_key: str,
        pipeline: str | None = None,
    ) -> SubmittedJob:
        raise ProcessingServiceError(
            "No processing service is configured. "
            "Set PROCESSING_SERVICE_URL and PROCESSING_SERVICE_TOKEN to enable video processing."
        )
