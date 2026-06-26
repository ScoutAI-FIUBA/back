from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import unittest

from src.application.clip_collections.errors import CLIP_COLLECTION_NOT_FOUND, FORBIDDEN_TEAM_ACCESS, ClipCollectionError
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
        filename="goal.mp4",
        storage_key=f"key/{item_id}",
        cloudflare_url=f"https://cdn.local/{item_id}.mp4",
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
                filename=item.filename,
                storage_key=item.storage_key,
                cloudflare_url=item.cloudflare_url,
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

    def delete_item(self, *, item_id: str, collection_id: str, owner_user_id: str) -> bool:
        del owner_user_id
        existing = self.items.get(collection_id, [])
        next_items = [item for item in existing if item.id != item_id]
        deleted = len(next_items) != len(existing)
        self.items[collection_id] = next_items
        return deleted


class _Videos:
    def __init__(self, *, owner_user_id: str = "user-1") -> None:
        self.context = OwnedVideoContext(video_id="video-1", team_id="team-1", owner_user_id=owner_user_id)

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


class TestClipCollectionUseCases(unittest.TestCase):
    def test_create_and_add_batch_builds_hierarchical_storage_keys(self) -> None:
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
                        filename="goal 1.mp4",
                        cloudflare_url="https://cdn.local/goal-1.mp4",
                    ),
                    AddClipCommand(
                        user_id="user-1",
                        video_id="video-1",
                        collection_id=collection.id,
                        filename="../goal-2.mov",
                        cloudflare_url="https://cdn.local/goal-2.mov",
                    ),
                ],
            )
        )

        self.assertEqual(len(items), 2)
        self.assertIn("user/user-1/team/team-1/video/video-1/collection/", items[0].storage_key)
        self.assertTrue(items[0].storage_key.endswith("-goal-1.mp4"))
        self.assertTrue(items[1].storage_key.endswith("-goal-2.mov"))
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
                    filename="goal.mp4",
                    cloudflare_url="https://cdn.local/goal.mp4",
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
                    filename="goal.mp4",
                    cloudflare_url="https://cdn.local/goal.mp4",
                )
            )

        self.assertEqual(ctx.exception.code, CLIP_COLLECTION_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
