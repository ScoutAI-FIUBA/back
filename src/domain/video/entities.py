from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class VideoStatus(str, Enum):
    PENDING_UPLOAD = "PENDING_UPLOAD"
    READY = "READY"
    FAILED = "FAILED"
    DELETED = "DELETED"


@dataclass(frozen=True)
class Video:
    id: str
    team_id: str
    owner_user_id: str
    storage_key: str
    title: str
    description: str | None
    status: VideoStatus
    mime_type: str | None
    size_bytes: int | None
    duration_ms: int | None
    etag: str | None
    upload_expires_at: datetime | None
    multipart_upload_id: str | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    thumbnail_key: str | None = None
    match_id: str | None = None
