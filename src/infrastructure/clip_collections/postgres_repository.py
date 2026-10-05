from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from psycopg.rows import dict_row

from src.application.clip_collections.ports import PendingClipItem
from src.domain.clip_collections.entities import ClipCollection, ClipCollectionItem


class CursorLike(Protocol):
    def execute(self, query: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> Any: ...

    def fetchone(self) -> dict[str, Any] | tuple[Any, ...] | None: ...

    def fetchall(self) -> list[dict[str, Any]]: ...


class ConnectionLike(Protocol):
    def cursor(self, *args: Any, **kwargs: Any) -> CursorLike: ...


def _row_to_collection(row: dict[str, Any] | None) -> ClipCollection | None:
    if row is None:
        return None
    return ClipCollection(
        id=str(row["id"]),
        video_id=str(row["video_id"]),
        team_id=str(row["team_id"]),
        owner_user_id=row["owner_user_id"],
        name=row["name"],
        description=row.get("description"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_item(row: dict[str, Any] | None) -> ClipCollectionItem | None:
    if row is None:
        return None
    return ClipCollectionItem(
        id=str(row["id"]),
        collection_id=str(row["collection_id"]),
        start_ms=row["start_ms"],
        end_ms=row["end_ms"],
        description=row.get("description"),
        position=row["position"],
        created_at=row["created_at"],
    )


class PostgresClipCollectionRepository:
    def __init__(self, *, connection: ConnectionLike) -> None:
        self._connection = connection

    def create_collection(
        self,
        *,
        collection_id: str,
        video_id: str,
        team_id: str,
        owner_user_id: str,
        name: str,
        description: str | None,
    ) -> ClipCollection:
        now = datetime.now(timezone.utc)
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO clip_collections (
                    id, video_id, team_id, owner_user_id, name, description, created_at, updated_at
                ) VALUES (
                    %(id)s::uuid, %(video_id)s::uuid, %(team_id)s::uuid, %(owner_user_id)s, %(name)s, %(description)s, %(created_at)s, %(updated_at)s
                )
                RETURNING *
                """,
                {
                    "id": collection_id,
                    "video_id": video_id,
                    "team_id": team_id,
                    "owner_user_id": owner_user_id,
                    "name": name,
                    "description": description,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            row = cur.fetchone()
        return _row_to_collection(row)  # type: ignore[return-value]

    def list_by_video(self, *, video_id: str, owner_user_id: str) -> list[ClipCollection]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT *
                FROM clip_collections
                WHERE video_id = %(video_id)s::uuid
                  AND owner_user_id = %(owner_user_id)s
                ORDER BY created_at DESC
                """,
                {"video_id": video_id, "owner_user_id": owner_user_id},
            )
            return [collection for row in cur.fetchall() if (collection := _row_to_collection(row)) is not None]

    def get_by_id(self, *, collection_id: str, video_id: str, owner_user_id: str) -> ClipCollection | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT *
                FROM clip_collections
                WHERE id = %(collection_id)s::uuid
                  AND video_id = %(video_id)s::uuid
                  AND owner_user_id = %(owner_user_id)s
                """,
                {"collection_id": collection_id, "video_id": video_id, "owner_user_id": owner_user_id},
            )
            return _row_to_collection(cur.fetchone())

    def add_items(self, *, collection_id: str, owner_user_id: str, items: list[PendingClipItem]) -> list[ClipCollectionItem] | None:
        if not items:
            return []
        created: list[ClipCollectionItem] = []
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id
                FROM clip_collections
                WHERE id = %(collection_id)s::uuid
                  AND owner_user_id = %(owner_user_id)s
                FOR UPDATE
                """,
                {"collection_id": collection_id, "owner_user_id": owner_user_id},
            )
            locked_collection = cur.fetchone()
            if locked_collection is None:
                return None
            cur.execute(
                """
                SELECT COALESCE(MAX(position), 0) AS max_position
                FROM clip_collection_items i
                INNER JOIN clip_collections c ON c.id = i.collection_id
                WHERE i.collection_id = %(collection_id)s::uuid
                  AND c.owner_user_id = %(owner_user_id)s
                """,
                {"collection_id": collection_id, "owner_user_id": owner_user_id},
            )
            row = cur.fetchone()
            max_position = 0
            if isinstance(row, dict):
                max_position = int(row.get("max_position") or 0)
            elif row is not None:
                max_position = int(row[0])
            next_position = max_position + 1
            now = datetime.now(timezone.utc)
            for item in items:
                cur.execute(
                    """
                    INSERT INTO clip_collection_items (
                        id, collection_id, start_ms, end_ms, description, position, created_at
                    ) VALUES (
                        %(id)s::uuid, %(collection_id)s::uuid, %(start_ms)s, %(end_ms)s, %(description)s, %(position)s, %(created_at)s
                    )
                    RETURNING *
                    """,
                    {
                        "id": item.item_id,
                        "collection_id": collection_id,
                        "start_ms": item.start_ms,
                        "end_ms": item.end_ms,
                        "description": item.description,
                        "position": next_position,
                        "created_at": now,
                    },
                )
                created_row = cur.fetchone()
                next_position += 1
                entity = _row_to_item(created_row)
                if entity is not None:
                    created.append(entity)
        return created

    def list_items(self, *, collection_id: str, owner_user_id: str) -> list[ClipCollectionItem]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT i.*
                FROM clip_collection_items i
                INNER JOIN clip_collections c ON c.id = i.collection_id
                WHERE i.collection_id = %(collection_id)s::uuid
                  AND c.owner_user_id = %(owner_user_id)s
                ORDER BY i.position ASC, i.created_at ASC
                """,
                {"collection_id": collection_id, "owner_user_id": owner_user_id},
            )
            return [item for row in cur.fetchall() if (item := _row_to_item(row)) is not None]

    def get_item(self, *, item_id: str, collection_id: str, owner_user_id: str) -> ClipCollectionItem | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT i.*
                FROM clip_collection_items i
                INNER JOIN clip_collections c ON c.id = i.collection_id
                WHERE i.id = %(item_id)s::uuid
                  AND i.collection_id = %(collection_id)s::uuid
                  AND c.owner_user_id = %(owner_user_id)s
                """,
                {"item_id": item_id, "collection_id": collection_id, "owner_user_id": owner_user_id},
            )
            return _row_to_item(cur.fetchone())

    def update_item_description(
        self,
        *,
        item_id: str,
        collection_id: str,
        owner_user_id: str,
        description: str | None,
    ) -> ClipCollectionItem | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE clip_collection_items i
                SET description = %(description)s
                FROM clip_collections c
                WHERE i.id = %(item_id)s::uuid
                  AND i.collection_id = %(collection_id)s::uuid
                  AND c.id = i.collection_id
                  AND c.owner_user_id = %(owner_user_id)s
                RETURNING i.*
                """,
                {
                    "item_id": item_id,
                    "collection_id": collection_id,
                    "owner_user_id": owner_user_id,
                    "description": description,
                },
            )
            return _row_to_item(cur.fetchone())

    def delete_item(self, *, item_id: str, collection_id: str, owner_user_id: str) -> bool:
        with self._connection.cursor() as cur:
            cur.execute(
                """
                DELETE FROM clip_collection_items i
                USING clip_collections c
                WHERE i.id = %(item_id)s::uuid
                  AND i.collection_id = %(collection_id)s::uuid
                  AND c.id = i.collection_id
                  AND c.owner_user_id = %(owner_user_id)s
                """,
                {"item_id": item_id, "collection_id": collection_id, "owner_user_id": owner_user_id},
            )
            return cur.rowcount > 0
