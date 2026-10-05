from __future__ import annotations

from dataclasses import dataclass

from src.application.clip_collections.errors import (
    CLIP_EXPORT_FAILED,
    CLIP_COLLECTION_ITEM_NOT_FOUND,
    CLIP_COLLECTION_NOT_FOUND,
    FORBIDDEN_TEAM_ACCESS,
    INVALID_CLIP_RANGE,
    VIDEO_NOT_FOUND,
    ClipCollectionError,
)
from src.application.clip_collections.ports import (
    ClipExporterPort,
    ClipCollectionRepositoryPort,
    IdGeneratorPort,
    OwnedVideoContext,
    OwnedVideoLookupPort,
    PendingClipItem,
    UnitOfWorkPort,
)
from src.domain.clip_collections.entities import ClipCollection, ClipCollectionItem


MAX_CLIP_DURATION_MS = 30_000


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
    start_ms: int
    end_ms: int
    description: str | None


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


@dataclass(frozen=True)
class ExportClipItemCommand:
    user_id: str
    video_id: str
    collection_id: str
    item_id: str


@dataclass(frozen=True)
class UpdateClipDescriptionCommand:
    user_id: str
    video_id: str
    collection_id: str
    item_id: str
    description: str | None


def _raise_invalid_clip_range(*, start_ms: int, end_ms: int, duration_ms: int | None, reason: str) -> None:
    raise ClipCollectionError(
        code=INVALID_CLIP_RANGE,
        message="Invalid clip range",
        details={
            "start_ms": start_ms,
            "end_ms": end_ms,
            "video_duration_ms": duration_ms,
            "reason": reason,
        },
    )


def _validate_clip_range(*, ctx: OwnedVideoContext, start_ms: int, end_ms: int) -> None:
    if start_ms < 0:
        _raise_invalid_clip_range(
            start_ms=start_ms,
            end_ms=end_ms,
            duration_ms=ctx.duration_ms,
            reason="start_ms_must_be_non_negative",
        )
    if end_ms <= start_ms:
        _raise_invalid_clip_range(
            start_ms=start_ms,
            end_ms=end_ms,
            duration_ms=ctx.duration_ms,
            reason="end_ms_must_be_greater_than_start_ms",
        )
    if end_ms - start_ms > MAX_CLIP_DURATION_MS:
        _raise_invalid_clip_range(
            start_ms=start_ms,
            end_ms=end_ms,
            duration_ms=ctx.duration_ms,
            reason="clip_duration_exceeds_30_seconds",
        )
    if ctx.duration_ms is not None and end_ms > ctx.duration_ms:
        _raise_invalid_clip_range(
            start_ms=start_ms,
            end_ms=end_ms,
            duration_ms=ctx.duration_ms,
            reason="end_ms_exceeds_video_duration",
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
                item_id=self._ids.new_id(),
                start_ms=clip.start_ms,
                end_ms=clip.end_ms,
                description=clip.description,
            )
            for clip in command.clips
        ]
        for clip in normalized:
            _validate_clip_range(ctx=ctx, start_ms=clip.start_ms, end_ms=clip.end_ms)
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


class UpdateClipDescriptionUseCase:
    def __init__(
        self,
        *,
        collections: ClipCollectionRepositoryPort,
        videos: OwnedVideoLookupPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._collections = collections
        self._videos = videos
        self._uow = uow

    def execute(self, command: UpdateClipDescriptionCommand) -> ClipCollectionItem:
        ctx = _assert_owned_video(videos=self._videos, user_id=command.user_id, video_id=command.video_id)
        collection = self._collections.get_by_id(
            collection_id=command.collection_id,
            video_id=ctx.video_id,
            owner_user_id=ctx.owner_user_id,
        )
        if collection is None:
            raise ClipCollectionError(code=CLIP_COLLECTION_NOT_FOUND, message="Clip collection not found")
        with self._uow.transaction():
            updated = self._collections.update_item_description(
                item_id=command.item_id,
                collection_id=command.collection_id,
                owner_user_id=ctx.owner_user_id,
                description=command.description,
            )
        if updated is None:
            raise ClipCollectionError(code=CLIP_COLLECTION_ITEM_NOT_FOUND, message="Clip collection item not found")
        return updated


class ExportClipItemUseCase:
    def __init__(
        self,
        *,
        collections: ClipCollectionRepositoryPort,
        videos: OwnedVideoLookupPort,
        exporter: ClipExporterPort,
    ) -> None:
        self._collections = collections
        self._videos = videos
        self._exporter = exporter

    def execute(self, command: ExportClipItemCommand) -> str:
        ctx = _assert_owned_video(videos=self._videos, user_id=command.user_id, video_id=command.video_id)
        collection = self._collections.get_by_id(
            collection_id=command.collection_id,
            video_id=ctx.video_id,
            owner_user_id=ctx.owner_user_id,
        )
        if collection is None:
            raise ClipCollectionError(code=CLIP_COLLECTION_NOT_FOUND, message="Clip collection not found")
        item = self._collections.get_item(
            item_id=command.item_id,
            collection_id=command.collection_id,
            owner_user_id=ctx.owner_user_id,
        )
        if item is None:
            raise ClipCollectionError(code=CLIP_COLLECTION_ITEM_NOT_FOUND, message="Clip collection item not found")

        export_key = f"exports/{item.id}.mp4"
        try:
            if not self._exporter.export_exists(export_key=export_key):
                self._exporter.export_clip(
                    source_key=ctx.storage_key,
                    export_key=export_key,
                    start_ms=item.start_ms,
                    end_ms=item.end_ms,
                )
            return self._exporter.generate_download_url(export_key=export_key)
        except Exception as exc:
            raise ClipCollectionError(code=CLIP_EXPORT_FAILED, message="Clip export failed") from exc
