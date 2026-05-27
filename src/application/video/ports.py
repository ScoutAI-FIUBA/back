from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.application.common.ports import IdGeneratorPort, UnitOfWorkPort
from src.domain.video.entities import Video


class VideoStorageKeyConflictError(Exception):
    """Raised by repository when `storage_key` violates uniqueness."""


class VideoRepositoryPort(ABC):
    @abstractmethod
    def create_pending(
        self,
        *,
        video_id: str,
        team_id: str,
        owner_user_id: str,
        storage_key: str,
        title: str,
        description: str | None,
        upload_expires_at: datetime | None,
        multipart_upload_id: str,
    ) -> Video: ...

    @abstractmethod
    def complete_upload(
        self,
        *,
        video_id: str,
        team_id: str,
        mime_type: str | None,
        size_bytes: int | None,
        duration_ms: int | None,
        etag: str | None,
        multipart_upload_id: str,
    ) -> Video | None: ...

    @abstractmethod
    def fail_pending_upload(self, *, video_id: str, team_id: str, multipart_upload_id: str) -> Video | None: ...

    @abstractmethod
    def list_by_team(self, *, team_id: str, status: str | None = None) -> list[Video]: ...

    @abstractmethod
    def get_by_id(self, *, video_id: str, team_id: str) -> Video | None: ...

    @abstractmethod
    def update_metadata(
        self,
        *,
        video_id: str,
        team_id: str,
        title: str | None,
        description: str | None,
    ) -> Video | None: ...

    @abstractmethod
    def replace_players(self, *, video_id: str, player_ids: list[str]) -> None: ...

    @abstractmethod
    def players_belong_to_team(self, *, team_id: str, player_ids: list[str]) -> bool: ...

    @abstractmethod
    def soft_delete(self, *, video_id: str, team_id: str) -> Video | None: ...


class VideoStoragePort(ABC):
    @abstractmethod
    def init_multipart_upload(self, *, key: str, content_type: str | None = None) -> str: ...

    @abstractmethod
    def generate_presigned_upload_part_url(
        self,
        *,
        key: str,
        upload_id: str,
        part_number: int,
        expires_in: int = 900,
    ) -> str: ...

    @abstractmethod
    def complete_multipart_upload(
        self,
        *,
        key: str,
        upload_id: str,
        parts: list[dict[str, str | int]],
    ) -> str | None: ...

    @abstractmethod
    def abort_multipart_upload(self, *, key: str, upload_id: str) -> None: ...

    @abstractmethod
    def generate_presigned_url(self, key: str, expires_in: int = 900) -> str: ...

    @abstractmethod
    def delete_video(self, key: str) -> None: ...


class TeamAccessPort(ABC):
    @abstractmethod
    def assert_access(self, *, user_id: str, team_id: str) -> None: ...


__all__ = ["IdGeneratorPort", "TeamAccessPort", "UnitOfWorkPort", "VideoRepositoryPort", "VideoStoragePort"]
