from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ClipCollection:
    id: str
    video_id: str
    team_id: str
    owner_user_id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ClipCollectionItem:
    id: str
    collection_id: str
    filename: str
    storage_key: str
    cloudflare_url: str
    position: int
    created_at: datetime
