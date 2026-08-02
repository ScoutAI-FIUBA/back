from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import unittest

from src.application.clip_collections.errors import (
    CLIP_EXPORT_FAILED,
    CLIP_COLLECTION_ITEM_NOT_FOUND,
    CLIP_COLLECTION_NOT_FOUND,
    FORBIDDEN_TEAM_ACCESS,
    INVALID_CLIP_RANGE,
    VIDEO_NOT_FOUND,
    ClipCollectionError,
)
from src.application.clip_collections.ports import OwnedVideoContext
from src.application.clip_collections.use_cases import (
    AddClipBatchCommand,
    AddClipCommand,
    AddClipBatchUseCase,
    AddClipUseCase,
    CreateClipCollectionCommand,
    CreateClipCollectionUseCase,
    DeleteClipCollectionItemCommand,
    DeleteClipCollectionItemUseCase,
    ExportClipItemCommand,
    ExportClipItemUseCase,
    GetClipCollectionDetailUseCase,
)
from src.domain.clip_collections.entities import ClipCollection, ClipCollectionItem


def _collection(collection_id: str = "collection-1") -> ClipCollection:
    now = datetime.now(timezone.utc)
    return ClipCollection(
        id=collection_id,
        video_id="video-1",
        team_id="team-1",
        owner_user_id="user-1",
        name="Highlights",
        description=None,
        created_at=now,
        updated_at=now,
    )


def _item(item_id: str, position: int = 1) -> ClipCollectionItem:
    return ClipCollectionItem(
        id=item_id,
        collection_id="collection-1",
        start_ms=5_000,
        end_ms=10_000,
        position=position,
        created_at=datetime.now(timezone.utc),
    )


class _CollectionsRepo:
    def __init__(self) -> None:
        self.collections: dict[str, ClipCollection] = {}
        self.items: dict[str, list[ClipCollectionItem]] = {}
        self.missing_on_add = False

    def create_collection(self, **kwargs) -> ClipCollection:
        created = ClipCollection(
            id=kwargs["collection_id"],
            video_id=kwargs["video_id"],
            team_id=kwargs["team_id"],
            owner_user_id=kwargs["owner_user_id"],
            name=kwargs["name"],
            description=kwargs["description"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.collections[created.id] = created
        self.items.setdefault(created.id, [])
        return created

    def list_by_video(self, *, video_id: str, owner_user_id: str) -> list[ClipCollection]:
        return [c for c in self.collections.values() if c.video_id == video_id and c.owner_user_id == owner_user_id]

    def get_by_id(self, *, collection_id: str, video_id: str, owner_user_id: str) -> ClipCollection | None:
        collection = self.collections.get(collection_id)
        if collection is None or collection.video_id != video_id or collection.owner_user_id != owner_user_id:
            return None
        return collection

    def add_items(self, *, collection_id: str, owner_user_id: str, items):
        del owner_user_id
        if self.missing_on_add:
            return None
        stored = self.items.setdefault(collection_id, [])
        created = [
            ClipCollectionItem(
                id=item.item_id,
                collection_id=collection_id,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                position=len(stored) + index + 1,
                created_at=datetime.now(timezone.utc),
            )
            for index, item in enumerate(items)
        ]
        stored.extend(created)
        return created

    def list_items(self, *, collection_id: str, owner_user_id: str):
        del owner_user_id
        return list(self.items.get(collection_id, []))

    def get_item(self, *, item_id: str, collection_id: str, owner_user_id: str):
        del owner_user_id
        for item in self.items.get(collection_id, []):
            if item.id == item_id:
                return item
        return None

    def delete_item(self, *, item_id: str, collection_id: str, owner_user_id: str) -> bool:
        del owner_user_id
        existing = self.items.get(collection_id, [])
        next_items = [item for item in existing if item.id != item_id]
        deleted = len(next_items) != len(existing)
        self.items[collection_id] = next_items
        return deleted


class _Videos:
    def __init__(self, *, owner_user_id: str = "user-1", duration_ms: int | None = 60_000, storage_key: str = "videos/source.mp4") -> None:
        self.context = OwnedVideoContext(
            video_id="video-1",
            team_id="team-1",
            owner_user_id=owner_user_id,
            duration_ms=duration_ms,
            storage_key=storage_key,
        )

    def get_video_context(self, *, video_id: str) -> OwnedVideoContext | None:
        return self.context if video_id == self.context.video_id else None


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


class _Exporter:
    def __init__(self, *, exists: bool = False, should_fail: bool = False) -> None:
        self.exists = exists
        self.should_fail = should_fail
        self.calls: list[tuple[str, str, int, int]] = []

    def export_exists(self, *, export_key: str) -> bool:
        self.last_exists_key = export_key
        return self.exists

    def export_clip(self, *, source_key: str, export_key: str, start_ms: int, end_ms: int) -> None:
        if self.should_fail:
            raise RuntimeError("ffmpeg failed")
        self.calls.append((source_key, export_key, start_ms, end_ms))

    def generate_download_url(self, *, export_key: str, expires_in: int = 3600) -> str:
        return f"https://download.local/{export_key}?exp={expires_in}"


class TestClipCollectionUseCases(unittest.TestCase):
    def test_create_and_add_batch_persists_timestamp_ranges_in_order(self) -> None:
        repo = _CollectionsRepo()
        create_use_case = CreateClipCollectionUseCase(collections=repo, videos=_Videos(), ids=_Ids(), uow=_Uow())
        collection = create_use_case.execute(
            CreateClipCollectionCommand(user_id="user-1", video_id="video-1", name="Highlights", description=None)
        )

        batch_use_case = AddClipBatchUseCase(collections=repo, videos=_Videos(), ids=_Ids(), uow=_Uow())
        items = batch_use_case.execute(
            AddClipBatchCommand(
                user_id="user-1",
                video_id="video-1",
                collection_id=collection.id,
                clips=[
                    AddClipCommand(
                        user_id="user-1",
                        video_id="video-1",
                        collection_id=collection.id,
                        start_ms=5_000,
                        end_ms=10_000,
                    ),
                    AddClipCommand(
                        user_id="user-1",
                        video_id="video-1",
                        collection_id=collection.id,
                        start_ms=10_000,
                        end_ms=15_000,
                    ),
                ],
            )
        )

        self.assertEqual(len(items), 2)
        self.assertEqual((items[0].start_ms, items[0].end_ms), (5_000, 10_000))
        self.assertEqual((items[1].start_ms, items[1].end_ms), (10_000, 15_000))
        self.assertEqual([item.position for item in items], [1, 2])

    def test_get_detail_and_delete_missing_item_maps_domain_errors(self) -> None:
        repo = _CollectionsRepo()
        repo.collections["collection-1"] = _collection()
        repo.items["collection-1"] = [_item("item-1")]

        detail_use_case = GetClipCollectionDetailUseCase(collections=repo, videos=_Videos())
        collection, items = detail_use_case.execute(user_id="user-1", video_id="video-1", collection_id="collection-1")
        self.assertEqual(collection.id, "collection-1")
        self.assertEqual(len(items), 1)

        delete_use_case = DeleteClipCollectionItemUseCase(collections=repo, videos=_Videos(), uow=_Uow())
        with self.assertRaisesRegex(ClipCollectionError, "Clip collection item not found"):
            delete_use_case.execute(
                DeleteClipCollectionItemCommand(
                    user_id="user-1",
                    video_id="video-1",
                    collection_id="collection-1",
                    item_id="missing-item",
                )
            )

    def test_forbidden_owner_and_missing_collection_raise_expected_codes(self) -> None:
        repo = _CollectionsRepo()
        repo.collections["collection-1"] = _collection()

        with self.assertRaises(ClipCollectionError) as forbidden_ctx:
            AddClipUseCase(
                batch_use_case=AddClipBatchUseCase(collections=repo, videos=_Videos(owner_user_id="other-user"), ids=_Ids(), uow=_Uow())
            ).execute(
                AddClipCommand(
                    user_id="user-1",
                    video_id="video-1",
                    collection_id="collection-1",
                    start_ms=1_000,
                    end_ms=5_000,
                )
            )
        self.assertEqual(forbidden_ctx.exception.code, FORBIDDEN_TEAM_ACCESS)

        with self.assertRaises(ClipCollectionError) as missing_ctx:
            DeleteClipCollectionItemUseCase(collections=repo, videos=_Videos(), uow=_Uow()).execute(
                DeleteClipCollectionItemCommand(
                    user_id="user-1",
                    video_id="video-1",
                    collection_id="missing-collection",
                    item_id="item-1",
                )
            )
        self.assertEqual(missing_ctx.exception.code, CLIP_COLLECTION_NOT_FOUND)

    def test_add_clip_maps_deleted_collection_race_to_not_found(self) -> None:
        repo = _CollectionsRepo()
        repo.collections["collection-1"] = _collection()
        repo.missing_on_add = True

        with self.assertRaises(ClipCollectionError) as ctx:
            AddClipUseCase(batch_use_case=AddClipBatchUseCase(collections=repo, videos=_Videos(), ids=_Ids(), uow=_Uow())).execute(
                AddClipCommand(
                    user_id="user-1",
                    video_id="video-1",
                    collection_id="collection-1",
                    start_ms=1_000,
                    end_ms=5_000,
                )
            )

        self.assertEqual(ctx.exception.code, CLIP_COLLECTION_NOT_FOUND)

    def test_add_clip_rejects_invalid_ranges_atomically(self) -> None:
        repo = _CollectionsRepo()
        repo.collections["collection-1"] = _collection()
        use_case = AddClipBatchUseCase(collections=repo, videos=_Videos(), ids=_Ids(), uow=_Uow())

        for start_ms, end_ms in ((-1, 100), (10_000, 10_000), (0, 30_001), (55_000, 60_001)):
            with self.assertRaises(ClipCollectionError) as ctx:
                use_case.execute(
                    AddClipBatchCommand(
                        user_id="user-1",
                        video_id="video-1",
                        collection_id="collection-1",
                        clips=[
                            AddClipCommand(
                                user_id="user-1",
                                video_id="video-1",
                                collection_id="collection-1",
                                start_ms=start_ms,
                                end_ms=end_ms,
                            )
                        ],
                    )
                )
            self.assertEqual(ctx.exception.code, INVALID_CLIP_RANGE)

        self.assertEqual(repo.items.get("collection-1", []), [])

    def test_add_clip_skips_duration_upper_bound_when_video_duration_is_null(self) -> None:
        repo = _CollectionsRepo()
        repo.collections["collection-1"] = _collection()
        use_case = AddClipUseCase(batch_use_case=AddClipBatchUseCase(collections=repo, videos=_Videos(duration_ms=None), ids=_Ids(), uow=_Uow()))

        item = use_case.execute(
            AddClipCommand(
                user_id="user-1",
                video_id="video-1",
                collection_id="collection-1",
                start_ms=50_000,
                end_ms=60_000,
            )
        )

        self.assertEqual((item.start_ms, item.end_ms), (50_000, 60_000))

    def test_export_clip_uses_cache_hit_without_regeneration(self) -> None:
        repo = _CollectionsRepo()
        repo.collections["collection-1"] = _collection()
        repo.items["collection-1"] = [_item("item-1")]
        exporter = _Exporter(exists=True)

        download_url = ExportClipItemUseCase(collections=repo, videos=_Videos(), exporter=exporter).execute(
            ExportClipItemCommand(
                user_id="user-1",
                video_id="video-1",
                collection_id="collection-1",
                item_id="item-1",
            )
        )

        self.assertEqual(download_url, "https://download.local/exports/item-1.mp4?exp=3600")
        self.assertEqual(exporter.calls, [])

    def test_export_clip_generates_on_cache_miss(self) -> None:
        repo = _CollectionsRepo()
        repo.collections["collection-1"] = _collection()
        repo.items["collection-1"] = [_item("item-1")]
        exporter = _Exporter(exists=False)

        ExportClipItemUseCase(collections=repo, videos=_Videos(storage_key="videos/source.mp4"), exporter=exporter).execute(
            ExportClipItemCommand(
                user_id="user-1",
                video_id="video-1",
                collection_id="collection-1",
                item_id="item-1",
            )
        )

        self.assertEqual(exporter.calls, [("videos/source.mp4", "exports/item-1.mp4", 5_000, 10_000)])

    def test_export_clip_maps_not_found_and_forbidden_errors(self) -> None:
        repo = _CollectionsRepo()
        repo.collections["collection-1"] = _collection()
        repo.items["collection-1"] = [_item("item-1")]

        with self.assertRaises(ClipCollectionError) as forbidden_ctx:
            ExportClipItemUseCase(collections=repo, videos=_Videos(owner_user_id="other-user"), exporter=_Exporter()).execute(
                ExportClipItemCommand(
                    user_id="user-1",
                    video_id="video-1",
                    collection_id="collection-1",
                    item_id="item-1",
                )
            )
        self.assertEqual(forbidden_ctx.exception.code, FORBIDDEN_TEAM_ACCESS)

        with self.assertRaises(ClipCollectionError) as missing_collection_ctx:
            ExportClipItemUseCase(collections=repo, videos=_Videos(), exporter=_Exporter()).execute(
                ExportClipItemCommand(
                    user_id="user-1",
                    video_id="video-1",
                    collection_id="missing",
                    item_id="item-1",
                )
            )
        self.assertEqual(missing_collection_ctx.exception.code, CLIP_COLLECTION_NOT_FOUND)

        with self.assertRaises(ClipCollectionError) as missing_item_ctx:
            ExportClipItemUseCase(collections=repo, videos=_Videos(), exporter=_Exporter()).execute(
                ExportClipItemCommand(
                    user_id="user-1",
                    video_id="video-1",
                    collection_id="collection-1",
                    item_id="missing-item",
                )
            )
        self.assertEqual(missing_item_ctx.exception.code, CLIP_COLLECTION_ITEM_NOT_FOUND)

    def test_export_clip_maps_infrastructure_failures_to_domain_error(self) -> None:
        repo = _CollectionsRepo()
        repo.collections["collection-1"] = _collection()
        repo.items["collection-1"] = [_item("item-1")]

        with self.assertRaises(ClipCollectionError) as ctx:
            ExportClipItemUseCase(collections=repo, videos=_Videos(), exporter=_Exporter(should_fail=True)).execute(
                ExportClipItemCommand(
                    user_id="user-1",
                    video_id="video-1",
                    collection_id="collection-1",
                    item_id="item-1",
                )
            )
        self.assertEqual(ctx.exception.code, CLIP_EXPORT_FAILED)

    def test_export_clip_returns_video_not_found_when_source_video_is_unknown(self) -> None:
        repo = _CollectionsRepo()

        class _MissingVideos:
            def get_video_context(self, *, video_id: str):
                del video_id
                return None

        with self.assertRaises(ClipCollectionError) as ctx:
            ExportClipItemUseCase(collections=repo, videos=_MissingVideos(), exporter=_Exporter()).execute(
                ExportClipItemCommand(
                    user_id="user-1",
                    video_id="video-1",
                    collection_id="collection-1",
                    item_id="item-1",
                )
            )
        self.assertEqual(ctx.exception.code, VIDEO_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
