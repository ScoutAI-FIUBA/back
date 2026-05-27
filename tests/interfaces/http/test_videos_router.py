from __future__ import annotations

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


class _GetUC:
    def execute(self, **_kwargs):
        raise VideoError(code=FORBIDDEN_TEAM_ACCESS, message="Forbidden team access")


class _UpdateUC:
    def execute(self, _command):
        raise VideoError(code=FORBIDDEN_TEAM_ACCESS, message="Forbidden team access")


class _DeleteUC:
    def execute(self, _command):
        raise VideoError(code=FORBIDDEN_TEAM_ACCESS, message="Forbidden team access")


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


if __name__ == "__main__":
    unittest.main()
