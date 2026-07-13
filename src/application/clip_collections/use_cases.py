from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re

from src.application.clip_collections.errors import (
    CLIP_COLLECTION_ITEM_NOT_FOUND,
    CLIP_COLLECTION_NOT_FOUND,
    FORBIDDEN_TEAM_ACCESS,
    VIDEO_NOT_FOUND,
    ClipCollectionError,
)
from src.application.clip_collections.ports import (
    ClipCollectionRepositoryPort,
    IdGeneratorPort,
    OwnedVideoContext,
    OwnedVideoLookupPort,
    PendingClipItem,
    UnitOfWorkPort,
)
from src.domain.clip_collections.entities import ClipCollection, ClipCollectionItem


_SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class CreateClipCollectionCommand:
    user_id: str
    video_id: str
    name: str
    description: str | None


@dataclass(frozen=True)
class AddClipCommand:
    user_id: str
    video_id: str
    collection_id: str
    filename: str
    cloudflare_url: str


@dataclass(frozen=True)
class AddClipBatchCommand:
    user_id: str
    video_id: str
    collection_id: str
    clips: list[AddClipCommand]


@dataclass(frozen=True)
class DeleteClipCollectionItemCommand:
    user_id: str
    video_id: str
    collection_id: str
    item_id: str


def _sanitize_filename(filename: str) -> str:
    candidate = PurePosixPath(filename).name.strip()
    if not candidate:
        return "clip"
    sanitized = _SAFE_FILENAME_PATTERN.sub("-", candidate)
    sanitized = sanitized.strip(".-")
    return sanitized or "clip"


def _build_storage_key(*, ctx: OwnedVideoContext, collection_id: str, clip_id: str, filename: str) -> str:
    return (
        f"user/{ctx.owner_user_id}/team/{ctx.team_id}/video/{ctx.video_id}/"
        f"collection/{collection_id}/clips/{clip_id}-{_sanitize_filename(filename)}"
    )


def _assert_owned_video(*, videos: OwnedVideoLookupPort, user_id: str, video_id: str) -> OwnedVideoContext:
    context = videos.get_video_context(video_id=video_id)
    if context is None:
        raise ClipCollectionError(code=VIDEO_NOT_FOUND, message="Video not found")
    if context.owner_user_id != user_id:
        raise ClipCollectionError(code=FORBIDDEN_TEAM_ACCESS, message="Forbidden team access")
    return context


class CreateClipCollectionUseCase:
    def __init__(
        self,
        *,
        collections: ClipCollectionRepositoryPort,
        videos: OwnedVideoLookupPort,
        ids: IdGeneratorPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._collections = collections
        self._videos = videos
        self._ids = ids
        self._uow = uow

    def execute(self, command: CreateClipCollectionCommand) -> ClipCollection:
        ctx = _assert_owned_video(videos=self._videos, user_id=command.user_id, video_id=command.video_id)
        with self._uow.transaction():
            return self._collections.create_collection(
                collection_id=self._ids.new_id(),
                video_id=ctx.video_id,
                team_id=ctx.team_id,
                owner_user_id=ctx.owner_user_id,
                name=command.name,
                description=command.description,
            )


class ListClipCollectionsUseCase:
    def __init__(self, *, collections: ClipCollectionRepositoryPort, videos: OwnedVideoLookupPort) -> None:
        self._collections = collections
        self._videos = videos

    def execute(self, *, user_id: str, video_id: str) -> list[ClipCollection]:
        ctx = _assert_owned_video(videos=self._videos, user_id=user_id, video_id=video_id)
        return self._collections.list_by_video(video_id=ctx.video_id, owner_user_id=ctx.owner_user_id)


class GetClipCollectionDetailUseCase:
    def __init__(self, *, collections: ClipCollectionRepositoryPort, videos: OwnedVideoLookupPort) -> None:
        self._collections = collections
        self._videos = videos

    def execute(self, *, user_id: str, video_id: str, collection_id: str) -> tuple[ClipCollection, list[ClipCollectionItem]]:
        ctx = _assert_owned_video(videos=self._videos, user_id=user_id, video_id=video_id)
        collection = self._collections.get_by_id(
            collection_id=collection_id,
            video_id=ctx.video_id,
            owner_user_id=ctx.owner_user_id,
        )
        if collection is None:
            raise ClipCollectionError(code=CLIP_COLLECTION_NOT_FOUND, message="Clip collection not found")
        items = self._collections.list_items(collection_id=collection_id, owner_user_id=ctx.owner_user_id)
        return collection, items


class AddClipBatchUseCase:
    def __init__(
        self,
        *,
        collections: ClipCollectionRepositoryPort,
        videos: OwnedVideoLookupPort,
        ids: IdGeneratorPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._collections = collections
        self._videos = videos
        self._ids = ids
        self._uow = uow

    def execute(self, command: AddClipBatchCommand) -> list[ClipCollectionItem]:
        ctx = _assert_owned_video(videos=self._videos, user_id=command.user_id, video_id=command.video_id)
        collection = self._collections.get_by_id(
            collection_id=command.collection_id,
            video_id=ctx.video_id,
            owner_user_id=ctx.owner_user_id,
        )
        if collection is None:
            raise ClipCollectionError(code=CLIP_COLLECTION_NOT_FOUND, message="Clip collection not found")
        normalized = [
            PendingClipItem(
                item_id=(item_id := self._ids.new_id()),
                filename=clip.filename,
                cloudflare_url=clip.cloudflare_url,
                storage_key=_build_storage_key(
                    ctx=ctx,
                    collection_id=command.collection_id,
                    clip_id=item_id,
                    filename=clip.filename,
                ),
            )
            for clip in command.clips
        ]
        with self._uow.transaction():
            created = self._collections.add_items(
                collection_id=command.collection_id,
                owner_user_id=ctx.owner_user_id,
                items=normalized,
            )
        if created is None:
            raise ClipCollectionError(code=CLIP_COLLECTION_NOT_FOUND, message="Clip collection not found")
        return created


class AddClipUseCase:
    def __init__(self, *, batch_use_case: AddClipBatchUseCase) -> None:
        self._batch_use_case = batch_use_case

    def execute(self, command: AddClipCommand) -> ClipCollectionItem:
        [item] = self._batch_use_case.execute(
            AddClipBatchCommand(user_id=command.user_id, video_id=command.video_id, collection_id=command.collection_id, clips=[command])
        )
        return item


class DeleteClipCollectionItemUseCase:
    def __init__(self, *, collections: ClipCollectionRepositoryPort, videos: OwnedVideoLookupPort, uow: UnitOfWorkPort) -> None:
        self._collections = collections
        self._videos = videos
        self._uow = uow

    def execute(self, command: DeleteClipCollectionItemCommand) -> None:
        ctx = _assert_owned_video(videos=self._videos, user_id=command.user_id, video_id=command.video_id)
        collection = self._collections.get_by_id(
            collection_id=command.collection_id,
            video_id=ctx.video_id,
            owner_user_id=ctx.owner_user_id,
        )
        if collection is None:
            raise ClipCollectionError(code=CLIP_COLLECTION_NOT_FOUND, message="Clip collection not found")
        with self._uow.transaction():
            deleted = self._collections.delete_item(
                item_id=command.item_id,
                collection_id=command.collection_id,
                owner_user_id=ctx.owner_user_id,
            )
        if not deleted:
            raise ClipCollectionError(code=CLIP_COLLECTION_ITEM_NOT_FOUND, message="Clip collection item not found")
