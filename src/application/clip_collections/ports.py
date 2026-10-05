from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.application.common.ports import IdGeneratorPort, UnitOfWorkPort
from src.domain.clip_collections.entities import ClipCollection, ClipCollectionItem


@dataclass(frozen=True)
class OwnedVideoContext:
    video_id: str
    team_id: str
    owner_user_id: str
    duration_ms: int | None
    storage_key: str


@dataclass(frozen=True)
class PendingClipItem:
    item_id: str
    start_ms: int
    end_ms: int
    description: str | None


class ClipCollectionRepositoryPort(ABC):
    @abstractmethod
    def create_collection(
        self,
        *,
        collection_id: str,
        video_id: str,
        team_id: str,
        owner_user_id: str,
        name: str,
        description: str | None,
    ) -> ClipCollection: ...

    @abstractmethod
    def list_by_video(self, *, video_id: str, owner_user_id: str) -> list[ClipCollection]: ...

    @abstractmethod
    def get_by_id(self, *, collection_id: str, video_id: str, owner_user_id: str) -> ClipCollection | None: ...

    @abstractmethod
    def add_items(
        self,
        *,
        collection_id: str,
        owner_user_id: str,
        items: list[PendingClipItem],
    ) -> list[ClipCollectionItem] | None: ...

    @abstractmethod
    def list_items(self, *, collection_id: str, owner_user_id: str) -> list[ClipCollectionItem]: ...

    @abstractmethod
    def get_item(self, *, item_id: str, collection_id: str, owner_user_id: str) -> ClipCollectionItem | None: ...

    @abstractmethod
    def update_item_description(
        self,
        *,
        item_id: str,
        collection_id: str,
        owner_user_id: str,
        description: str | None,
    ) -> ClipCollectionItem | None: ...

    @abstractmethod
    def delete_item(self, *, item_id: str, collection_id: str, owner_user_id: str) -> bool: ...


class ClipExporterPort(ABC):
    @abstractmethod
    def export_exists(self, *, export_key: str) -> bool: ...

    @abstractmethod
    def export_clip(self, *, source_key: str, export_key: str, start_ms: int, end_ms: int) -> None: ...

    @abstractmethod
    def generate_download_url(self, *, export_key: str, expires_in: int | None = None) -> str: ...


class OwnedVideoLookupPort(ABC):
    @abstractmethod
    def get_video_context(self, *, video_id: str) -> OwnedVideoContext | None: ...


__all__ = [
    "ClipExporterPort",
    "ClipCollectionRepositoryPort",
    "IdGeneratorPort",
    "OwnedVideoContext",
    "OwnedVideoLookupPort",
    "PendingClipItem",
    "UnitOfWorkPort",
]
