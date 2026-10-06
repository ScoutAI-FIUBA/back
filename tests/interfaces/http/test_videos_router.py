from __future__ import annotations

from datetime import datetime, timezone
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.video.errors import FORBIDDEN_TEAM_ACCESS, STORAGE_DELETE_FAILED, TEAM_NOT_FOUND, VideoError
from src.interfaces.http.routes.videos_router import create_videos_router


class _InitUC:
    def execute(self, _command):
        return (
            type("Video", (), {"id": "v1", "storage_key": "videos/t/k", "upload_expires_at": None, "status": type("S", (), {"value": "PENDING_UPLOAD"})()})(),
            "upload-1",
            [{"part_number": 1, "presigned_part_url": "https://part/1"}],
        )


class _CompleteUC:
    def execute(self, _command):
        raise VideoError(code=FORBIDDEN_TEAM_ACCESS, message="Forbidden team access")


class _AbortUC:
    def execute(self, _command):
        raise VideoError(code=FORBIDDEN_TEAM_ACCESS, message="Forbidden team access")


class _ListUC:
    def execute(self, **_kwargs):
        raise VideoError(code=FORBIDDEN_TEAM_ACCESS, message="Forbidden team access")


class _ListOkUC:
    def execute(self, **_kwargs):
        return [_ReadyVideo()]


class _GetUC:
    def execute(self, **_kwargs):
        raise VideoError(code=FORBIDDEN_TEAM_ACCESS, message="Forbidden team access")


class _UpdateUC:
    def execute(self, _command):
        raise VideoError(code=FORBIDDEN_TEAM_ACCESS, message="Forbidden team access")


class _DeleteUC:
    def execute(self, _command):
        raise VideoError(code=FORBIDDEN_TEAM_ACCESS, message="Forbidden team access")


class _ReadyVideo:
    id = "v1"
    team_id = "t1"
    owner_user_id = "u1"
    storage_key = "videos/t1/v1"
    title = "Clip"
    description = None
    mime_type = None
    size_bytes = None
    duration_ms = None
    etag = None
    upload_expires_at = None
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    thumbnail_key = None

    class _Status:
        value = "READY"

    status = _Status()


class _GetWithThumbnailUC:
    def execute(self, **_kwargs):
        return _ReadyVideo(), "https://play.local/videos/t1/v1", "https://play.local/thumbnails/t1/v1.jpg"


class _GetWithNullThumbnailUC:
    def execute(self, **_kwargs):
        return _ReadyVideo(), "https://play.local/videos/t1/v1", None


class _CompleteOkUC:
    def execute(self, _command):
        return _ReadyVideo()


def _client_with(*, get_uc, complete_uc, list_uc=None) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request, call_next):
        request.state.user_id = "user-1"
        return await call_next(request)

    app.include_router(
        create_videos_router(
            init_upload_use_case=_InitUC(),
            complete_upload_use_case=complete_uc,
            abort_upload_use_case=_AbortUC(),
            list_videos_use_case=list_uc or _ListUC(),
            get_video_use_case=get_uc,
            update_video_use_case=_UpdateUC(),
            delete_video_use_case=_DeleteUC(),
        )
    )
    return TestClient(app)


class TestVideosRouter(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()

        @app.middleware("http")
        async def _inject_user(request, call_next):
            request.state.user_id = "user-1"
            return await call_next(request)

        app.include_router(
            create_videos_router(
                init_upload_use_case=_InitUC(),
                complete_upload_use_case=_CompleteUC(),
                abort_upload_use_case=_AbortUC(),
                list_videos_use_case=_ListUC(),
                get_video_use_case=_GetUC(),
                update_video_use_case=_UpdateUC(),
                delete_video_use_case=_DeleteUC(),
            )
        )
        self.client = TestClient(app)

    def test_init_returns_multipart_contract(self) -> None:
        response = self.client.post(
            "/videos/upload/init",
            json={"team_id": "00000000-0000-4000-8000-000000000001", "title": "Clip", "part_count": 1},
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["upload_id"], "upload-1")
        self.assertEqual(body["parts"][0]["part_number"], 1)

    def test_authz_unauthorized_team_access_matrix_returns_403(self) -> None:
        checks = [
            (
                self.client.post,
                "/videos/00000000-0000-4000-8000-000000000010/upload/complete",
                {
                    "json": {
                        "team_id": "00000000-0000-4000-8000-000000000001",
                        "upload_id": "u",
                        "parts": [{"part_number": 1, "etag": "e"}],
                    }
                },
            ),
            (
                self.client.post,
                "/videos/00000000-0000-4000-8000-000000000010/upload/abort",
                {"json": {"team_id": "00000000-0000-4000-8000-000000000001", "upload_id": "u"}},
            ),
            (self.client.get, "/videos", {"params": {"team_id": "00000000-0000-4000-8000-000000000001"}}),
            (
                self.client.get,
                "/videos/00000000-0000-4000-8000-000000000010",
                {"params": {"team_id": "00000000-0000-4000-8000-000000000001"}},
            ),
            (
                self.client.patch,
                "/videos/00000000-0000-4000-8000-000000000010",
                {"json": {"team_id": "00000000-0000-4000-8000-000000000001", "title": "X"}},
            ),
            (
                self.client.delete,
                "/videos/00000000-0000-4000-8000-000000000010",
                {"params": {"team_id": "00000000-0000-4000-8000-000000000001"}},
            ),
        ]
        for method, path, kwargs in checks:
            response = method(path, **kwargs)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], FORBIDDEN_TEAM_ACCESS)

    def test_get_video_returns_presigned_thumbnail_url_when_present(self) -> None:
        client = _client_with(get_uc=_GetWithThumbnailUC(), complete_uc=_CompleteUC())

        response = client.get(
            "/videos/00000000-0000-4000-8000-000000000010",
            params={"team_id": "00000000-0000-4000-8000-000000000001"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["presigned_thumbnail_url"], "https://play.local/thumbnails/t1/v1.jpg")
        self.assertEqual(body["presigned_playback_url"], "https://play.local/videos/t1/v1")

    def test_get_video_returns_null_thumbnail_url_when_absent(self) -> None:
        client = _client_with(get_uc=_GetWithNullThumbnailUC(), complete_uc=_CompleteUC())

        response = client.get(
            "/videos/00000000-0000-4000-8000-000000000010",
            params={"team_id": "00000000-0000-4000-8000-000000000001"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["presigned_thumbnail_url"])

    def test_list_videos_does_not_expose_thumbnail_fields(self) -> None:
        # Non-goal: the list endpoint must not gain any thumbnail field.
        client = _client_with(
            get_uc=_GetWithNullThumbnailUC(),
            complete_uc=_CompleteUC(),
            list_uc=_ListOkUC(),
        )

        response = client.get(
            "/videos",
            params={"team_id": "00000000-0000-4000-8000-000000000001"},
        )

        self.assertEqual(response.status_code, 200)
        items = response.json()["videos"]
        self.assertEqual(len(items), 1)
        for item in items:
            self.assertNotIn("thumbnail_key", item)
            self.assertNotIn("presigned_thumbnail_url", item)
            self.assertFalse(any("thumbnail" in key for key in item))

    def test_complete_upload_still_returns_200_when_thumbnail_missing(self) -> None:
        # The use case swallows generation failure; the router only sees a READY video.
        client = _client_with(get_uc=_GetWithNullThumbnailUC(), complete_uc=_CompleteOkUC())

        response = client.post(
            "/videos/00000000-0000-4000-8000-000000000010/upload/complete",
            json={
                "team_id": "00000000-0000-4000-8000-000000000001",
                "upload_id": "u",
                "parts": [{"part_number": 1, "etag": "e"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["video"]["status"], "READY")


if __name__ == "__main__":
    unittest.main()
