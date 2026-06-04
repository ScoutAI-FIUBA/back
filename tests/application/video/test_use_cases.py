from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import unittest

from src.application.video.errors import (
    FORBIDDEN_TEAM_ACCESS,
    PLAYER_TEAM_MISMATCH,
    STORAGE_DELETE_FAILED,
    TEAM_NOT_FOUND,
    UPLOAD_NOT_INITIALIZED,
    VIDEO_NOT_READY,
    VIDEO_STORAGE_KEY_CONFLICT,
    VideoError,
)
from src.application.video.ports import VideoStorageKeyConflictError
from src.application.video.use_cases import (
    AbortVideoUploadCommand,
    AbortVideoUploadUseCase,
    CompleteVideoUploadCommand,
    CompleteVideoUploadUseCase,
    DeleteVideoCommand,
    DeleteVideoUseCase,
    GetVideoUseCase,
    InitVideoUploadCommand,
    InitVideoUploadUseCase,
    UpdateVideoCommand,
    UpdateVideoUseCase,
)
from src.domain.video.entities import Video, VideoStatus


def _video(*, video_id: str, team_id: str, status: VideoStatus = VideoStatus.PENDING_UPLOAD) -> Video:
    now = datetime.now(timezone.utc)
    return Video(
        id=video_id,
        team_id=team_id,
        owner_user_id="user-1",
        storage_key=f"videos/{team_id}/{video_id}",
        title="Video",
        description=None,
        status=status,
        mime_type=None,
        size_bytes=None,
        duration_ms=None,
        etag=None,
        upload_expires_at=None,
        multipart_upload_id=None,
        deleted_at=None,
        created_at=now,
        updated_at=now,
    )


class _Repo:
    def __init__(self) -> None:
        self.by_id: dict[str, Video] = {}
        self.raise_storage_key_conflict = False
        self.failed_uploads: list[tuple[str, str, str]] = []

    def create_pending(self, **kwargs) -> Video:
        if self.raise_storage_key_conflict:
            raise VideoStorageKeyConflictError("duplicate storage key")
        created = _video(video_id=kwargs["video_id"], team_id=kwargs["team_id"], status=VideoStatus.PENDING_UPLOAD)
        created = replace(
            created,
            upload_expires_at=kwargs.get("upload_expires_at"),
            multipart_upload_id=kwargs.get("multipart_upload_id"),
        )
        self.by_id[created.id] = created
        return created

    def complete_upload(self, **kwargs) -> Video | None:
        found = self.by_id.get(kwargs["video_id"])
        if (
            found is None
            or found.team_id != kwargs["team_id"]
            or found.status != VideoStatus.PENDING_UPLOAD
            or found.multipart_upload_id != kwargs["multipart_upload_id"]
        ):
            return None
        completed = replace(
            found,
            status=VideoStatus.READY,
            mime_type=kwargs["mime_type"],
            size_bytes=kwargs["size_bytes"],
            duration_ms=kwargs["duration_ms"],
            etag=kwargs["etag"],
            multipart_upload_id=None,
        )
        self.by_id[completed.id] = completed
        return completed

    def list_by_team(self, *, team_id: str, status: str | None = None) -> list[Video]:
        videos = [video for video in self.by_id.values() if video.team_id == team_id and video.deleted_at is None]
        if status is not None:
            return [video for video in videos if video.status.value == status]
        return videos

    def get_by_id(self, *, video_id: str, team_id: str) -> Video | None:
        video = self.by_id.get(video_id)
        if video is None or video.team_id != team_id or video.deleted_at is not None:
            return None
        return video

    def update_metadata(self, **kwargs) -> Video | None:
        video = self.get_by_id(video_id=kwargs["video_id"], team_id=kwargs["team_id"])
        if video is None:
            return None
        updated = replace(
            video,
            title=kwargs["title"] if kwargs["title"] is not None else video.title,
            description=kwargs["description"] if kwargs["description"] is not None else video.description,
        )
        self.by_id[updated.id] = updated
        return updated

    def replace_players(self, *, video_id: str, player_ids: list[str]) -> None:
        del video_id, player_ids

    def players_belong_to_team(self, *, team_id: str, player_ids: list[str]) -> bool:
        del team_id
        return "cross-team-player" not in player_ids

    def soft_delete(self, *, video_id: str, team_id: str) -> Video | None:
        video = self.get_by_id(video_id=video_id, team_id=team_id)
        if video is None:
            return None
        deleted = replace(video, status=VideoStatus.DELETED, deleted_at=datetime.now(timezone.utc))
        self.by_id[deleted.id] = deleted
        return deleted

    def fail_pending_upload(self, *, video_id: str, team_id: str, multipart_upload_id: str) -> Video | None:
        video = self.get_by_id(video_id=video_id, team_id=team_id)
        if video is None:
            return None
        self.failed_uploads.append((video_id, team_id, multipart_upload_id))
        failed = replace(video, status=VideoStatus.FAILED, multipart_upload_id=None)
        self.by_id[failed.id] = failed
        return failed


class _Storage:
    def __init__(self) -> None:
        self.fail_delete = False

    def init_multipart_upload(self, *, key: str, content_type: str | None = None) -> str:
        del key, content_type
        return "upload-id-1"

    def generate_presigned_upload_part_url(
        self,
        *,
        key: str,
        upload_id: str,
        part_number: int,
        expires_in: int = 900,
    ) -> str:
        del expires_in
        return f"https://upload.local/{key}/{upload_id}/part/{part_number}"

    def complete_multipart_upload(
        self,
        *,
        key: str,
        upload_id: str,
        parts: list[dict[str, str | int]],
    ) -> str | None:
        del key, upload_id, parts
        return "etag-final"

    def abort_multipart_upload(self, *, key: str, upload_id: str) -> None:
        del key, upload_id

    def generate_presigned_url(self, key: str, expires_in: int = 900) -> str:
        del expires_in
        return f"https://play.local/{key}"

    def delete_video(self, key: str) -> None:
        if self.fail_delete:
            raise RuntimeError(f"delete failed for {key}")


class _TeamAccess:
    def __init__(self) -> None:
        self.allowed_teams = {"team-1"}

    def assert_access(self, *, user_id: str, team_id: str) -> None:
        del user_id
        if team_id not in self.allowed_teams:
            raise VideoError(code=TEAM_NOT_FOUND, message="Team not found")


class _Ids:
    def __init__(self) -> None:
        self.n = 0

    def new_id(self) -> str:
        self.n += 1
        return f"id-{self.n}"


class _Uow:
    @contextmanager
    def transaction(self):
        yield


class TestVideoUseCases(unittest.TestCase):
    def test_init_upload_creates_pending_video_and_multipart_contract(self) -> None:
        repo = _Repo()
        use_case = InitVideoUploadUseCase(
            videos=repo,
            storage=_Storage(),
            team_access=_TeamAccess(),
            ids=_Ids(),
            uow=_Uow(),
        )

        video, upload_id, parts = use_case.execute(
            InitVideoUploadCommand(
                user_id="u1",
                team_id="team-1",
                title="Matchday",
                description="desc",
                content_type="video/mp4",
                part_count=3,
            )
        )

        self.assertEqual(video.status, VideoStatus.PENDING_UPLOAD)
        self.assertTrue(video.storage_key.startswith("videos/team-1/"))
        self.assertEqual(upload_id, "upload-id-1")
        self.assertEqual(len(parts), 3)
        self.assertIsNotNone(video.upload_expires_at)
        self.assertEqual(video.multipart_upload_id, "upload-id-1")

    def test_init_upload_unknown_team_raises_404_semantic_error(self) -> None:
        use_case = InitVideoUploadUseCase(
            videos=_Repo(),
            storage=_Storage(),
            team_access=_TeamAccess(),
            ids=_Ids(),
            uow=_Uow(),
        )
        with self.assertRaises(VideoError) as ctx:
            use_case.execute(
                InitVideoUploadCommand(
                    user_id="u1",
                    team_id="unknown-team",
                    title="Matchday",
                    description=None,
                    content_type=None,
                    part_count=2,
                )
            )
        self.assertEqual(ctx.exception.code, TEAM_NOT_FOUND)

    def test_init_upload_maps_duplicate_storage_key_conflict(self) -> None:
        repo = _Repo()
        repo.raise_storage_key_conflict = True
        use_case = InitVideoUploadUseCase(
            videos=repo,
            storage=_Storage(),
            team_access=_TeamAccess(),
            ids=_Ids(),
            uow=_Uow(),
        )
        with self.assertRaises(VideoError) as ctx:
            use_case.execute(
                InitVideoUploadCommand(
                    user_id="u1", team_id="team-1", title="Matchday", description=None, content_type=None, part_count=2
                )
            )
        self.assertEqual(ctx.exception.code, VIDEO_STORAGE_KEY_CONFLICT)

    def test_complete_without_pending_init_raises_upload_not_initialized(self) -> None:
        use_case = CompleteVideoUploadUseCase(videos=_Repo(), storage=_Storage(), team_access=_TeamAccess(), uow=_Uow())

        with self.assertRaises(VideoError) as ctx:
            use_case.execute(
                CompleteVideoUploadCommand(
                    user_id="u1",
                    team_id="team-1",
                    video_id="missing",
                    mime_type="video/mp4",
                    size_bytes=1024,
                    duration_ms=1000,
                    multipart_upload_id="upload-id-1",
                    parts=[{"PartNumber": 1, "ETag": "etag-1"}],
                )
            )
        self.assertEqual(ctx.exception.code, UPLOAD_NOT_INITIALIZED)

    def test_abort_upload_marks_video_failed(self) -> None:
        repo = _Repo()
        repo.by_id["v1"] = replace(_video(video_id="v1", team_id="team-1"), multipart_upload_id="upload-id-1")
        use_case = AbortVideoUploadUseCase(videos=repo, storage=_Storage(), team_access=_TeamAccess(), uow=_Uow())

        use_case.execute(
            AbortVideoUploadCommand(
                user_id="u1", team_id="team-1", video_id="v1", multipart_upload_id="upload-id-1"
            )
        )

        self.assertEqual(repo.by_id["v1"].status, VideoStatus.FAILED)

    def test_get_video_requires_ready_status(self) -> None:
        repo = _Repo()
        repo.by_id["v1"] = _video(video_id="v1", team_id="team-1", status=VideoStatus.PENDING_UPLOAD)
        use_case = GetVideoUseCase(videos=repo, storage=_Storage(), team_access=_TeamAccess())

        with self.assertRaises(VideoError) as ctx:
            use_case.execute(user_id="u1", team_id="team-1", video_id="v1")
        self.assertEqual(ctx.exception.code, VIDEO_NOT_READY)

    def test_update_rejects_cross_team_player_association(self) -> None:
        repo = _Repo()
        repo.by_id["v1"] = _video(video_id="v1", team_id="team-1", status=VideoStatus.READY)
        use_case = UpdateVideoUseCase(videos=repo, team_access=_TeamAccess(), uow=_Uow())

        with self.assertRaises(VideoError) as ctx:
            use_case.execute(
                UpdateVideoCommand(
                    user_id="u1",
                    team_id="team-1",
                    video_id="v1",
                    title="new",
                    description=None,
                    player_ids=["cross-team-player"],
                )
            )
        self.assertEqual(ctx.exception.code, PLAYER_TEAM_MISMATCH)

    def test_delete_storage_failure_maps_to_deterministic_error(self) -> None:
        repo = _Repo()
        repo.by_id["v1"] = _video(video_id="v1", team_id="team-1", status=VideoStatus.READY)
        storage = _Storage()
        storage.fail_delete = True
        use_case = DeleteVideoUseCase(videos=repo, storage=storage, team_access=_TeamAccess(), uow=_Uow())

        with self.assertRaises(VideoError) as ctx:
            use_case.execute(DeleteVideoCommand(user_id="u1", team_id="team-1", video_id="v1"))
        self.assertEqual(ctx.exception.code, STORAGE_DELETE_FAILED)


if __name__ == "__main__":
    unittest.main()
