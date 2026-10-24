from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.application.video.errors import (
    MATCH_NOT_FOUND,
    PLAYER_TEAM_MISMATCH,
    STORAGE_DELETE_FAILED,
    UPLOAD_NOT_INITIALIZED,
    VIDEO_NOT_FOUND,
    VIDEO_NOT_READY,
    VIDEO_STORAGE_KEY_CONFLICT,
    VIDEO_TEAM_NOT_IN_MATCH,
    VideoError,
)
from src.application.video.ports import (
    IdGeneratorPort,
    TeamAccessPort,
    ThumbnailGeneratorPort,
    UnitOfWorkPort,
    VideoMatchLookupPort,
    VideoRepositoryPort,
    VideoStorageKeyConflictError,
    VideoStoragePort,
)
from src.domain.video.entities import Video, VideoStatus

logger = logging.getLogger(__name__)


def _thumbnail_key(*, team_id: str, video_id: str) -> str:
    """Deterministic thumbnail object key derived from stable identifiers."""

    return f"thumbnails/{team_id}/{video_id}.jpg"


@dataclass(frozen=True)
class InitVideoUploadCommand:
    user_id: str
    team_id: str
    title: str
    description: str | None
    content_type: str | None
    part_count: int


@dataclass(frozen=True)
class CompleteVideoUploadCommand:
    user_id: str
    team_id: str
    video_id: str
    mime_type: str | None
    size_bytes: int | None
    duration_ms: int | None
    multipart_upload_id: str
    parts: list[dict[str, str | int]]


@dataclass(frozen=True)
class AbortVideoUploadCommand:
    user_id: str
    team_id: str
    video_id: str
    multipart_upload_id: str


@dataclass(frozen=True)
class UpdateVideoCommand:
    user_id: str
    team_id: str
    video_id: str
    title: str | None
    description: str | None
    player_ids: list[str] | None


@dataclass(frozen=True)
class DeleteVideoCommand:
    user_id: str
    team_id: str
    video_id: str


@dataclass(frozen=True)
class SetVideoMatchCommand:
    user_id: str
    team_id: str
    video_id: str
    match_id: str | None


class InitVideoUploadUseCase:
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        storage: VideoStoragePort,
        team_access: TeamAccessPort,
        ids: IdGeneratorPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._videos = videos
        self._storage = storage
        self._team_access = team_access
        self._ids = ids
        self._uow = uow

    def execute(self, command: InitVideoUploadCommand) -> tuple[Video, str, list[dict[str, object]]]:
        # Access is enforced before creating metadata to avoid dangling rows.
        self._team_access.assert_access(user_id=command.user_id, team_id=command.team_id)
        upload_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        storage_key = f"videos/{command.team_id}/{self._ids.new_id()}"
        multipart_upload_id = self._storage.init_multipart_upload(key=storage_key, content_type=command.content_type)
        try:
            with self._uow.transaction():
                video = self._videos.create_pending(
                    video_id=self._ids.new_id(),
                    team_id=command.team_id,
                    owner_user_id=command.user_id,
                    storage_key=storage_key,
                    title=command.title,
                    description=command.description,
                    upload_expires_at=upload_expires_at,
                    multipart_upload_id=multipart_upload_id,
                )
        except VideoStorageKeyConflictError as exc:
            raise VideoError(code=VIDEO_STORAGE_KEY_CONFLICT, message="Video storage key conflict") from exc
        parts: list[dict[str, object]] = []
        for part_number in range(1, command.part_count + 1):
            part_url = self._storage.generate_presigned_upload_part_url(
                key=video.storage_key,
                upload_id=multipart_upload_id,
                part_number=part_number,
            )
            parts.append({"part_number": part_number, "presigned_part_url": part_url})
        return video, multipart_upload_id, parts


class CompleteVideoUploadUseCase:
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        storage: VideoStoragePort,
        team_access: TeamAccessPort,
        thumbnail_generator: ThumbnailGeneratorPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._videos = videos
        self._storage = storage
        self._team_access = team_access
        self._thumbnail_generator = thumbnail_generator
        self._uow = uow

    def execute(self, command: CompleteVideoUploadCommand) -> Video:
        self._team_access.assert_access(user_id=command.user_id, team_id=command.team_id)
        # Load metadata first so multipart completion uses the canonical storage key.
        current = self._videos.get_by_id(video_id=command.video_id, team_id=command.team_id)
        if current is None:
            raise VideoError(code=UPLOAD_NOT_INITIALIZED, message="Upload not initialized")
        etag = self._storage.complete_multipart_upload(
            key=current.storage_key,
            upload_id=command.multipart_upload_id,
            parts=command.parts,
        )
        with self._uow.transaction():
            video = self._videos.complete_upload(
                video_id=command.video_id,
                team_id=command.team_id,
                mime_type=command.mime_type,
                size_bytes=command.size_bytes,
                duration_ms=command.duration_ms,
                etag=etag,
                multipart_upload_id=command.multipart_upload_id,
            )
        if video is None:
            raise VideoError(code=UPLOAD_NOT_INITIALIZED, message="Upload not initialized")
        return self._generate_thumbnail_best_effort(video)

    def _generate_thumbnail_best_effort(self, video: Video) -> Video:
        """Generates and persists a thumbnail without failing the upload.

        Any generator or persistence error is swallowed: the READY video is
        returned with ``thumbnail_key`` left null, and a later lazy GET can
        retry the backfill.
        """

        thumbnail_key = _thumbnail_key(team_id=video.team_id, video_id=video.id)
        try:
            self._thumbnail_generator.generate(source_key=video.storage_key, thumbnail_key=thumbnail_key)
            with self._uow.transaction():
                updated = self._videos.set_thumbnail_key(
                    video_id=video.id,
                    team_id=video.team_id,
                    thumbnail_key=thumbnail_key,
                )
        except Exception:
            return video
        return updated if updated is not None else video


class AbortVideoUploadUseCase:
    def __init__(self, *, videos: VideoRepositoryPort, storage: VideoStoragePort, team_access: TeamAccessPort, uow: UnitOfWorkPort) -> None:
        self._videos = videos
        self._storage = storage
        self._team_access = team_access
        self._uow = uow

    def execute(self, command: AbortVideoUploadCommand) -> None:
        self._team_access.assert_access(user_id=command.user_id, team_id=command.team_id)
        video = self._videos.get_by_id(video_id=command.video_id, team_id=command.team_id)
        if video is None:
            raise VideoError(code=UPLOAD_NOT_INITIALIZED, message="Upload not initialized")
        self._storage.abort_multipart_upload(key=video.storage_key, upload_id=command.multipart_upload_id)
        with self._uow.transaction():
            self._videos.fail_pending_upload(
                video_id=command.video_id,
                team_id=command.team_id,
                multipart_upload_id=command.multipart_upload_id,
            )


class ListVideosUseCase:
    def __init__(self, *, videos: VideoRepositoryPort, team_access: TeamAccessPort) -> None:
        self._videos = videos
        self._team_access = team_access

    def execute(self, *, user_id: str, team_id: str, status: str | None = None) -> list[Video]:
        self._team_access.assert_access(user_id=user_id, team_id=team_id)
        return self._videos.list_by_team(team_id=team_id, status=status)


class GetVideoUseCase:
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        storage: VideoStoragePort,
        team_access: TeamAccessPort,
        thumbnail_generator: ThumbnailGeneratorPort,
    ) -> None:
        self._videos = videos
        self._storage = storage
        self._team_access = team_access
        self._thumbnail_generator = thumbnail_generator

    def execute(self, *, user_id: str, team_id: str, video_id: str) -> tuple[Video, str, str | None]:
        self._team_access.assert_access(user_id=user_id, team_id=team_id)
        video = self._videos.get_by_id(video_id=video_id, team_id=team_id)
        if video is None:
            raise VideoError(code=VIDEO_NOT_FOUND, message="Video not found")
        if video.status != VideoStatus.READY:
            raise VideoError(code=VIDEO_NOT_READY, message="Video not ready")
        if video.thumbnail_key is None:
            video = self._backfill_thumbnail(video)
        thumbnail_url = (
            self._storage.generate_presigned_url(video.thumbnail_key)
            if video.thumbnail_key is not None
            else None
        )
        return video, self._storage.generate_presigned_url(video.storage_key), thumbnail_url

    def _backfill_thumbnail(self, video: Video) -> Video:
        """Lazily generates a missing thumbnail; failures are non-fatal.

        Concurrent GETs may duplicate work, but the deterministic key makes the
        write idempotent and a partial object is never observed by readers.
        """

        thumbnail_key = _thumbnail_key(team_id=video.team_id, video_id=video.id)
        try:
            self._thumbnail_generator.generate(source_key=video.storage_key, thumbnail_key=thumbnail_key)
            updated = self._videos.set_thumbnail_key(
                video_id=video.id,
                team_id=video.team_id,
                thumbnail_key=thumbnail_key,
            )
        except Exception:
            return video
        return updated if updated is not None else video


class UpdateVideoUseCase:
    def __init__(self, *, videos: VideoRepositoryPort, team_access: TeamAccessPort, uow: UnitOfWorkPort) -> None:
        self._videos = videos
        self._team_access = team_access
        self._uow = uow

    def execute(self, command: UpdateVideoCommand) -> Video:
        self._team_access.assert_access(user_id=command.user_id, team_id=command.team_id)
        with self._uow.transaction():
            video = self._videos.update_metadata(
                video_id=command.video_id,
                team_id=command.team_id,
                title=command.title,
                description=command.description,
            )
            if video is None:
                raise VideoError(code=VIDEO_NOT_FOUND, message="Video not found")
            if command.player_ids is not None:
                if not self._videos.players_belong_to_team(team_id=command.team_id, player_ids=command.player_ids):
                    raise VideoError(code=PLAYER_TEAM_MISMATCH, message="Player team mismatch")
                self._videos.replace_players(video_id=command.video_id, player_ids=command.player_ids)
        return video


class DeleteVideoUseCase:
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        storage: VideoStoragePort,
        team_access: TeamAccessPort,
        uow: UnitOfWorkPort,
        on_deleted: Callable[[str], None] | None = None,
    ) -> None:
        self._videos = videos
        self._storage = storage
        self._team_access = team_access
        self._uow = uow
        # Called with the video id once it is soft-deleted (the player stats stop counting
        # it). Best effort: it must never fail the delete.
        self._on_deleted = on_deleted

    def execute(self, command: DeleteVideoCommand) -> dict[str, object]:
        self._team_access.assert_access(user_id=command.user_id, team_id=command.team_id)
        with self._uow.transaction():
            video = self._videos.soft_delete(video_id=command.video_id, team_id=command.team_id)
        if video is None:
            raise VideoError(code=VIDEO_NOT_FOUND, message="Video not found")
        if self._on_deleted is not None:
            try:
                self._on_deleted(command.video_id)
            except Exception:  # noqa: BLE001 - best effort, see __init__
                logger.exception("Could not refresh player stats after deleting video %s", command.video_id)
        try:
            self._storage.delete_video(video.storage_key)
        except Exception as exc:
            raise VideoError(
                code=STORAGE_DELETE_FAILED,
                message="Storage deletion failed",
                details={"reason": str(exc)},
            ) from exc
        # Thumbnail cleanup is best-effort: a failure must not resurrect the
        # deleted source or fail the request. Null keys are skipped.
        if video.thumbnail_key is not None:
            with contextlib.suppress(Exception):
                self._storage.delete_video(video.thumbnail_key)
        return {"deleted": True, "compensation_pending": False}


class SetVideoMatchUseCase:
    """Links a video to one of the owner's matches, or clears the link (match_id None)."""

    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        matches: VideoMatchLookupPort,
        team_access: TeamAccessPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._videos = videos
        self._matches = matches
        self._team_access = team_access
        self._uow = uow

    def execute(self, command: SetVideoMatchCommand) -> Video:
        self._team_access.assert_access(user_id=command.user_id, team_id=command.team_id)
        with self._uow.transaction():
            video = self._videos.get_by_id(video_id=command.video_id, team_id=command.team_id)
            if video is None or video.status == VideoStatus.DELETED:
                raise VideoError(code=VIDEO_NOT_FOUND, message="Video not found")
            if command.match_id is not None:
                teams = self._matches.get_teams(match_id=command.match_id, owner_user_id=command.user_id)
                if teams is None:
                    raise VideoError(code=MATCH_NOT_FOUND, message="Match not found")
                if video.team_id not in teams:
                    raise VideoError(
                        code=VIDEO_TEAM_NOT_IN_MATCH,
                        message="The video's team does not play in this match",
                    )
            updated = self._videos.set_match(
                video_id=command.video_id,
                team_id=command.team_id,
                match_id=command.match_id,
            )
            if updated is None:
                raise VideoError(code=VIDEO_NOT_FOUND, message="Video not found")
        return updated
