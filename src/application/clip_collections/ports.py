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


@dataclass(frozen=True)
class PendingClipItem:
    item_id: str
    filename: str
    storage_key: str
    cloudflare_url: str


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
    def delete_item(self, *, item_id: str, collection_id: str, owner_user_id: str) -> bool: ...


class OwnedVideoLookupPort(ABC):
    @abstractmethod
    def get_video_context(self, *, video_id: str) -> OwnedVideoContext | None: ...


__all__ = [
    "ClipCollectionRepositoryPort",
    "IdGeneratorPort",
    "OwnedVideoContext",
    "OwnedVideoLookupPort",
    "PendingClipItem",
    "UnitOfWorkPort",
]
