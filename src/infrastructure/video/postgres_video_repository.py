from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

from src.application.video.ports import VideoStorageKeyConflictError
from src.application.clip_collections.ports import OwnedVideoContext
from src.domain.video.entities import Video, VideoStatus


class CursorLike(Protocol):
    def execute(self, query: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> Any: ...

    def fetchone(self) -> dict[str, Any] | tuple[Any, ...] | None: ...

    def fetchall(self) -> list[dict[str, Any]]: ...


class ConnectionLike(Protocol):
    def cursor(self, *args: Any, **kwargs: Any) -> CursorLike: ...


def _row_to_video(row: dict[str, Any] | None) -> Video | None:
    if row is None:
        return None
    return Video(
        id=str(row["id"]),
        team_id=str(row["team_id"]),
        owner_user_id=row["owner_user_id"],
        storage_key=row["storage_key"],
        title=row["title"],
        description=row.get("description"),
        status=VideoStatus(row["status"]),
        mime_type=row.get("mime_type"),
        size_bytes=row.get("size_bytes"),
        duration_ms=row.get("duration_ms"),
        etag=row.get("etag"),
        upload_expires_at=row.get("upload_expires_at"),
        multipart_upload_id=row.get("multipart_upload_id"),
        deleted_at=row.get("deleted_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PostgresVideoRepository:
    def __init__(self, *, connection: ConnectionLike) -> None:
        self._connection = connection

    def create_pending(self, **kwargs) -> Video:
        now = datetime.now(timezone.utc)
        params = {
            **kwargs,
            "status": VideoStatus.PENDING_UPLOAD.value,
            "created_at": now,
            "updated_at": now,
        }
        with self._connection.cursor(row_factory=dict_row) as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO videos (
                        id, team_id, owner_user_id, storage_key, title, description,
                        status, upload_expires_at, multipart_upload_id, created_at, updated_at
                    ) VALUES (
                        %(video_id)s::uuid, %(team_id)s::uuid, %(owner_user_id)s, %(storage_key)s,
                        %(title)s, %(description)s, %(status)s, %(upload_expires_at)s, %(multipart_upload_id)s,
                        %(created_at)s, %(updated_at)s
                    )
                    RETURNING *
                    """,
                    params,
                )
            except psycopg.errors.UniqueViolation as exc:
                # Normalize DB uniqueness violation to an application-level contract.
                raise VideoStorageKeyConflictError("Video storage key conflict") from exc
            row = cur.fetchone()
        return _row_to_video(row)  # type: ignore[return-value]

    def complete_upload(self, **kwargs) -> Video | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE videos
                SET status = %(ready)s,
                    mime_type = %(mime_type)s,
                    size_bytes = %(size_bytes)s,
                    duration_ms = %(duration_ms)s,
                    etag = %(etag)s,
                    multipart_upload_id = NULL,
                    updated_at = NOW()
                WHERE id = %(video_id)s::uuid
                  AND team_id = %(team_id)s::uuid
                  AND status = %(pending)s
                  AND multipart_upload_id = %(multipart_upload_id)s
                  AND deleted_at IS NULL
                RETURNING *
                """,
                {
                    **kwargs,
                    "ready": VideoStatus.READY.value,
                    "pending": VideoStatus.PENDING_UPLOAD.value,
                },
            )
            return _row_to_video(cur.fetchone())

    def list_by_team(self, *, team_id: str, status: str | None = None) -> list[Video]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            if status:
                cur.execute(
                    """
                    SELECT * FROM videos
                    WHERE team_id = %(team_id)s::uuid AND status = %(status)s AND deleted_at IS NULL
                    ORDER BY created_at DESC
                    """,
                    {"team_id": team_id, "status": status},
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM videos
                    WHERE team_id = %(team_id)s::uuid AND deleted_at IS NULL
                    ORDER BY created_at DESC
                    """,
                    {"team_id": team_id},
                )
            return [video for row in cur.fetchall() if (video := _row_to_video(row)) is not None]

    def get_by_id(self, *, video_id: str, team_id: str) -> Video | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM videos
                WHERE id = %(video_id)s::uuid AND team_id = %(team_id)s::uuid AND deleted_at IS NULL
                """,
                {"video_id": video_id, "team_id": team_id},
            )
            return _row_to_video(cur.fetchone())

    def update_metadata(self, **kwargs) -> Video | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE videos
                SET title = COALESCE(%(title)s, title),
                    description = COALESCE(%(description)s, description),
                    updated_at = NOW()
                WHERE id = %(video_id)s::uuid AND team_id = %(team_id)s::uuid AND deleted_at IS NULL
                RETURNING *
                """,
                kwargs,
            )
            return _row_to_video(cur.fetchone())

    def replace_players(self, *, video_id: str, player_ids: list[str]) -> None:
        with self._connection.cursor() as cur:
            cur.execute("DELETE FROM video_players WHERE video_id = %(video_id)s::uuid", {"video_id": video_id})
            for player_id in player_ids:
                cur.execute(
                    """
                    INSERT INTO video_players (video_id, player_id, created_at)
                    VALUES (%(video_id)s::uuid, %(player_id)s::uuid, NOW())
                    ON CONFLICT (video_id, player_id) DO NOTHING
                    """,
                    {"video_id": video_id, "player_id": player_id},
                )

    def players_belong_to_team(self, *, team_id: str, player_ids: list[str]) -> bool:
        if not player_ids:
            return True
        with self._connection.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM players
                WHERE id = ANY(%(player_ids)s::uuid[])
                  AND team_id = %(team_id)s::uuid
                """,
                {"player_ids": player_ids, "team_id": team_id},
            )
            row = cur.fetchone()
        count = int(row[0]) if row else 0
        return count == len(set(player_ids))

    def soft_delete(self, *, video_id: str, team_id: str) -> Video | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE videos
                SET status = %(deleted)s,
                    deleted_at = NOW(),
                    updated_at = NOW()
                WHERE id = %(video_id)s::uuid AND team_id = %(team_id)s::uuid AND deleted_at IS NULL
                RETURNING *
                """,
                {"video_id": video_id, "team_id": team_id, "deleted": VideoStatus.DELETED.value},
            )
            return _row_to_video(cur.fetchone())

    def fail_pending_upload(self, *, video_id: str, team_id: str, multipart_upload_id: str) -> Video | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE videos
                SET status = %(failed)s,
                    multipart_upload_id = NULL,
                    updated_at = NOW()
                WHERE id = %(video_id)s::uuid
                  AND team_id = %(team_id)s::uuid
                  AND status = %(pending)s
                  AND multipart_upload_id = %(multipart_upload_id)s
                  AND deleted_at IS NULL
                RETURNING *
                """,
                {
                    "video_id": video_id,
                    "team_id": team_id,
                    "multipart_upload_id": multipart_upload_id,
                    "failed": VideoStatus.FAILED.value,
                    "pending": VideoStatus.PENDING_UPLOAD.value,
                },
            )
            return _row_to_video(cur.fetchone())

    def get_video_context(self, *, video_id: str) -> OwnedVideoContext | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT v.id AS video_id, v.team_id, v.owner_user_id, v.duration_ms, v.storage_key
                FROM videos v
                INNER JOIN teams t ON t.id = v.team_id
                WHERE v.id = %(video_id)s::uuid
                  AND v.deleted_at IS NULL
                """,
                {"video_id": video_id},
            )
            row = cur.fetchone()
        if row is None:
            return None
        return OwnedVideoContext(
            video_id=str(row["video_id"]),
            team_id=str(row["team_id"]),
            owner_user_id=row["owner_user_id"],
            duration_ms=row["duration_ms"],
            storage_key=row["storage_key"],
        )
