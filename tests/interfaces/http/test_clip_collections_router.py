from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.clip_collections.errors import FORBIDDEN_TEAM_ACCESS, ClipCollectionError
from src.interfaces.http.routes.clip_collections_router import create_clip_collections_router


class _CreateUC:
    def execute(self, _command):
        return type(
            "Collection",
            (),
            {
                "id": "collection-1",
                "video_id": "video-1",
                "team_id": "team-1",
                "owner_user_id": "user-1",
                "name": "Highlights",
                "description": None,
                "created_at": __import__("datetime").datetime(2026, 1, 1),
                "updated_at": __import__("datetime").datetime(2026, 1, 1),
            },
        )()


class _ForbiddenUC:
    def execute(self, *_args, **_kwargs):
        raise ClipCollectionError(code=FORBIDDEN_TEAM_ACCESS, message="Forbidden team access")


class TestClipCollectionsRouter(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()

        @app.middleware("http")
        async def _inject_user(request, call_next):
            request.state.user_id = "user-1"
            return await call_next(request)

        app.include_router(
            create_clip_collections_router(
                create_collection_use_case=_CreateUC(),
                list_collections_use_case=_ForbiddenUC(),
                get_collection_detail_use_case=_ForbiddenUC(),
                add_clip_use_case=_ForbiddenUC(),
                add_clip_batch_use_case=_ForbiddenUC(),
                delete_item_use_case=_ForbiddenUC(),
            )
        )
        self.client = TestClient(app)

    def test_create_collection_returns_created_payload(self) -> None:
        response = self.client.post(
            "/videos/00000000-0000-4000-8000-000000000001/collections",
            json={"name": "Highlights"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["collection"]["id"], "collection-1")

    def test_owner_scoped_failures_return_403_matrix(self) -> None:
        checks = [
            (self.client.get, "/videos/00000000-0000-4000-8000-000000000001/collections", {}),
            (self.client.get, "/videos/00000000-0000-4000-8000-000000000001/collections/00000000-0000-4000-8000-000000000002", {}),
            (
                self.client.post,
                "/videos/00000000-0000-4000-8000-000000000001/collections/00000000-0000-4000-8000-000000000002/clips",
                {"json": {"filename": "goal.mp4", "cloudflare_url": "https://cdn.local/goal.mp4"}},
            ),
            (
                self.client.post,
                "/videos/00000000-0000-4000-8000-000000000001/collections/00000000-0000-4000-8000-000000000002/clips/batch",
                {"json": {"clips": [{"filename": "goal.mp4", "cloudflare_url": "https://cdn.local/goal.mp4"}]}},
            ),
            (
                self.client.delete,
                "/videos/00000000-0000-4000-8000-000000000001/collections/00000000-0000-4000-8000-000000000002/clips/00000000-0000-4000-8000-000000000003",
                {},
            ),
        ]
        for method, path, kwargs in checks:
            response = method(path, **kwargs)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], FORBIDDEN_TEAM_ACCESS)


if __name__ == "__main__":
    unittest.main()
