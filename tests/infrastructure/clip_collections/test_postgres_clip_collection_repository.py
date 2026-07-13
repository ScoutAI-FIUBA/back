from __future__ import annotations

from datetime import datetime, timezone
import unittest

from src.application.clip_collections.ports import PendingClipItem
from src.infrastructure.clip_collections.postgres_repository import PostgresClipCollectionRepository


class _Cursor:
    def __init__(self, connection: "_Connection") -> None:
        self._connection = connection
        self._fetchone_index = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self._connection.executed.append((" ".join(query.split()), params))

    def fetchone(self):
        row = self._connection.fetchone_results[self._fetchone_index]
        self._fetchone_index += 1
        return row

    def fetchall(self):
        return []


class _Connection:
    def __init__(self, fetchone_results):
        self.executed = []
        self.fetchone_results = fetchone_results

    def cursor(self, *args, **kwargs):
        return _Cursor(self)


class TestPostgresClipCollectionRepository(unittest.TestCase):
    def test_add_items_returns_none_when_collection_is_deleted_before_lock(self) -> None:
        connection = _Connection([None])
        repository = PostgresClipCollectionRepository(connection=connection)

        created = repository.add_items(
            collection_id="collection-1",
            owner_user_id="user-1",
            items=[
                PendingClipItem(
                    item_id="item-1",
                    filename="goal-1.mp4",
                    storage_key="clips/goal-1.mp4",
                    cloudflare_url="https://cdn.local/goal-1.mp4",
                )
            ],
        )

        self.assertIsNone(created)
        self.assertEqual(len(connection.executed), 1)
        self.assertIn("FOR UPDATE", connection.executed[0][0])

    def test_add_items_uses_named_aggregate_value_for_next_position(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        connection = _Connection(
            [
                {"id": "collection-1"},
                {"max_position": 2},
                {
                    "id": "item-1",
                    "collection_id": "collection-1",
                    "filename": "goal-1.mp4",
                    "storage_key": "clips/goal-1.mp4",
                    "cloudflare_url": "https://cdn.local/goal-1.mp4",
                    "position": 3,
                    "created_at": now,
                },
                {
                    "id": "item-2",
                    "collection_id": "collection-1",
                    "filename": "goal-2.mp4",
                    "storage_key": "clips/goal-2.mp4",
                    "cloudflare_url": "https://cdn.local/goal-2.mp4",
                    "position": 4,
                    "created_at": now,
                },
            ]
        )
        repository = PostgresClipCollectionRepository(connection=connection)

        created = repository.add_items(
            collection_id="collection-1",
            owner_user_id="user-1",
            items=[
                PendingClipItem(
                    item_id="item-1",
                    filename="goal-1.mp4",
                    storage_key="clips/goal-1.mp4",
                    cloudflare_url="https://cdn.local/goal-1.mp4",
                ),
                PendingClipItem(
                    item_id="item-2",
                    filename="goal-2.mp4",
                    storage_key="clips/goal-2.mp4",
                    cloudflare_url="https://cdn.local/goal-2.mp4",
                ),
            ],
        )

        self.assertEqual([item.position for item in created], [3, 4])
        self.assertIn("FOR UPDATE", connection.executed[0][0])
        self.assertIn("AS max_position", connection.executed[1][0])
        self.assertEqual(connection.executed[2][1]["position"], 3)
        self.assertEqual(connection.executed[3][1]["position"], 4)


if __name__ == "__main__":
    unittest.main()
