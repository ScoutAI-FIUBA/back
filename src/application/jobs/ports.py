from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.application.common.ports import IdGeneratorPort, UnitOfWorkPort
from src.application.video.ports import TeamAccessPort
from src.domain.jobs.entities import ProcessingJob


class ActiveJobExistsError(Exception):
    """Raised by the repository when a video already has a job in flight.

    Enforced by a partial unique index rather than a read-then-write check, so
    two simultaneous requests cannot both pass. GPU time is the most expensive
    resource here, so this is a correctness requirement, not a nicety.
    """


class JobRepositoryPort(ABC):
    @abstractmethod
    def create_queued(
        self,
        *,
        job_id: str,
        video_id: str,
        team_id: str,
        requested_by_user_id: str,
        results_key: str,
    ) -> ProcessingJob: ...

    @abstractmethod
    def attach_external_id(self, *, job_id: str, external_job_id: str) -> ProcessingJob | None: ...

    @abstractmethod
    def mark_failed(self, *, job_id: str, error_message: str) -> ProcessingJob | None: ...

    @abstractmethod
    def get_by_id_unscoped(self, *, job_id: str) -> ProcessingJob | None:
        """Look up a job without a team filter.

        Used only by the processing-service callback, which authenticates with a
        shared service token and therefore has no user or team context.
        """

    @abstractmethod
    def mark_running(self, *, job_id: str, progress_percent: int | None) -> ProcessingJob | None: ...

    @abstractmethod
    def mark_done(
        self,
        *,
        job_id: str,
        results_key: str | None,
        artifacts: list[str] | None = None,
        summary: dict | None = None,
    ) -> ProcessingJob | None: ...

    @abstractmethod
    def get_by_id(self, *, job_id: str, team_id: str) -> ProcessingJob | None: ...

    @abstractmethod
    def list_by_video(self, *, video_id: str, team_id: str) -> list[ProcessingJob]: ...

    @abstractmethod
    def find_active_for_video(self, *, video_id: str) -> ProcessingJob | None: ...


@dataclass(frozen=True)
class SubmittedJob:
    """What the processing service returns when it accepts a job."""

    external_job_id: str


class ProcessingServiceError(Exception):
    """Raised when the processing service is unreachable or rejects the request."""


class ProcessingServicePort(ABC):
    """Hands a video to whatever actually runs the GPU pipeline.

    Deliberately abstract: this app should not know or care that the other side
    is Modal. It also means the whole job lifecycle can be developed and tested
    against a fake, with no GPU service deployed.
    """

    @abstractmethod
    def submit(
        self,
        *,
        job_id: str,
        video_storage_key: str,
        results_key: str,
        pipeline: str | None = None,
    ) -> SubmittedJob: ...


class ArtifactUrlsUnavailableError(Exception):
    """Raised when download URLs cannot be produced, e.g. storage is unconfigured.

    A deployment problem, not a client mistake, so callers turn it into a 503
    rather than letting it surface as an unhandled 500.
    """


class ArtifactUrlSignerPort(ABC):
    """Mints time-limited download URLs for stored artifacts.

    Signing is a local operation over the key and credentials — it makes no
    request to the object store and does not require the object to exist. This
    app therefore never reads a job's outputs; it only tells the browser where
    to get them.
    """

    @abstractmethod
    def presign(self, *, key: str, expires_in: int) -> str: ...


class VideoLookupPort(ABC):
    """Minimal read access to videos, so jobs need not depend on the video module."""

    @abstractmethod
    def get_ready_video(self, *, video_id: str, team_id: str) -> tuple[str, str] | None:
        """Return `(video_id, storage_key)` when the video exists and is READY.

        Returns None when the video does not exist. Raises nothing for a video
        that exists but is not READY — that is reported separately so callers can
        distinguish "no such video" from "not uploaded yet".
        """

    @abstractmethod
    def exists(self, *, video_id: str, team_id: str) -> bool: ...


__all__ = [
    "ActiveJobExistsError",
    "ArtifactUrlSignerPort",
    "ArtifactUrlsUnavailableError",
    "IdGeneratorPort",
    "JobRepositoryPort",
    "ProcessingServiceError",
    "ProcessingServicePort",
    "SubmittedJob",
    "TeamAccessPort",
    "UnitOfWorkPort",
    "VideoLookupPort",
]
