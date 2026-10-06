from __future__ import annotations

from datetime import datetime, timezone
import unittest

from src.infrastructure.video.postgres_video_repository import PostgresVideoRepository


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


def _row(**overrides):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = {
        "id": "11111111-1111-4111-8111-111111111111",
        "team_id": "22222222-2222-4222-8222-222222222222",
        "owner_user_id": "user-1",
        "storage_key": "videos/team/video",
        "title": "Video",
        "description": None,
        "status": "READY",
        "mime_type": None,
        "size_bytes": None,
        "duration_ms": None,
        "etag": None,
        "upload_expires_at": None,
        "multipart_upload_id": None,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
        "thumbnail_key": "thumbnails/team/video.jpg",
    }
    row.update(overrides)
    return row


class TestPostgresVideoRepositoryThumbnail(unittest.TestCase):
    def test_row_mapper_reads_thumbnail_key(self) -> None:
        connection = _Connection([_row()])
        repository = PostgresVideoRepository(connection=connection)

        video = repository.get_by_id(video_id="video", team_id="team")

        assert video is not None
        self.assertEqual(video.thumbnail_key, "thumbnails/team/video.jpg")
        self.assertIn("FROM videos", connection.executed[0][0])

    def test_row_mapper_tolerates_missing_thumbnail_key(self) -> None:
        row = _row()
        del row["thumbnail_key"]
        connection = _Connection([row])
        repository = PostgresVideoRepository(connection=connection)

        video = repository.get_by_id(video_id="video", team_id="team")

        assert video is not None
        self.assertIsNone(video.thumbnail_key)

    def test_set_thumbnail_key_updates_owner_scoped_row(self) -> None:
        connection = _Connection([_row(thumbnail_key="thumbnails/team/video.jpg")])
        repository = PostgresVideoRepository(connection=connection)

        video = repository.set_thumbnail_key(
            video_id="video",
            team_id="team",
            thumbnail_key="thumbnails/team/video.jpg",
        )

        assert video is not None
        self.assertEqual(video.thumbnail_key, "thumbnails/team/video.jpg")
        query, params = connection.executed[0]
        self.assertIn("UPDATE videos", query)
        self.assertIn("thumbnail_key = %(thumbnail_key)s", query)
        self.assertIn("RETURNING *", query)
        self.assertEqual(params["video_id"], "video")
        self.assertEqual(params["team_id"], "team")
        self.assertEqual(params["thumbnail_key"], "thumbnails/team/video.jpg")

    def test_set_thumbnail_key_returns_none_for_missing_row(self) -> None:
        connection = _Connection([None])
        repository = PostgresVideoRepository(connection=connection)

        result = repository.set_thumbnail_key(video_id="missing", team_id="team", thumbnail_key="thumbnails/team/v.jpg")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
