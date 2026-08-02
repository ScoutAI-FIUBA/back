from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.clip_collections.errors import CLIP_EXPORT_FAILED, FORBIDDEN_TEAM_ACCESS, INVALID_CLIP_RANGE, ClipCollectionError
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


class _InvalidRangeUC:
    def execute(self, *_args, **_kwargs):
        raise ClipCollectionError(code=INVALID_CLIP_RANGE, message="Invalid clip range")


class _ExportUC:
    def execute(self, *_args, **_kwargs):
        return "https://download.local/exports/item-1.mp4"


class _ExportFailureUC:
    def execute(self, *_args, **_kwargs):
        raise ClipCollectionError(code=CLIP_EXPORT_FAILED, message="Clip export failed")


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
                export_clip_item_use_case=_ExportUC(),
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
                {"json": {"start_ms": 1000, "end_ms": 5000}},
            ),
            (
                self.client.post,
                "/videos/00000000-0000-4000-8000-000000000001/collections/00000000-0000-4000-8000-000000000002/clips/batch",
                {"json": {"clips": [{"start_ms": 1000, "end_ms": 5000}]}},
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

    def test_add_clip_returns_invalid_range_error_payload(self) -> None:
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
                add_clip_use_case=_InvalidRangeUC(),
                add_clip_batch_use_case=_ForbiddenUC(),
                delete_item_use_case=_ForbiddenUC(),
                export_clip_item_use_case=_ExportUC(),
            )
        )
        client = TestClient(app)

        response = client.post(
            "/videos/00000000-0000-4000-8000-000000000001/collections/00000000-0000-4000-8000-000000000002/clips",
            json={"start_ms": 5000, "end_ms": 4000},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], INVALID_CLIP_RANGE)

    def test_add_clip_negative_start_reaches_domain_invalid_range_contract(self) -> None:
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
                add_clip_use_case=_InvalidRangeUC(),
                add_clip_batch_use_case=_ForbiddenUC(),
                delete_item_use_case=_ForbiddenUC(),
                export_clip_item_use_case=_ExportUC(),
            )
        )
        client = TestClient(app)

        response = client.post(
            "/videos/00000000-0000-4000-8000-000000000001/collections/00000000-0000-4000-8000-000000000002/clips",
            json={"start_ms": -1, "end_ms": 1000},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], INVALID_CLIP_RANGE)

    def test_add_clip_batch_negative_start_reaches_domain_invalid_range_contract(self) -> None:
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
                add_clip_batch_use_case=_InvalidRangeUC(),
                delete_item_use_case=_ForbiddenUC(),
                export_clip_item_use_case=_ExportUC(),
            )
        )
        client = TestClient(app)

        response = client.post(
            "/videos/00000000-0000-4000-8000-000000000001/collections/00000000-0000-4000-8000-000000000002/clips/batch",
            json={"clips": [{"start_ms": -1, "end_ms": 1000}]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], INVALID_CLIP_RANGE)

    def test_export_clip_returns_download_url(self) -> None:
        response = self.client.post(
            "/videos/00000000-0000-4000-8000-000000000001/collections/00000000-0000-4000-8000-000000000002/clips/00000000-0000-4000-8000-000000000003/export"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["download_url"], "https://download.local/exports/item-1.mp4")

    def test_export_clip_maps_gateway_failures_to_502(self) -> None:
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
                add_clip_use_case=_InvalidRangeUC(),
                add_clip_batch_use_case=_ForbiddenUC(),
                delete_item_use_case=_ForbiddenUC(),
                export_clip_item_use_case=_ExportFailureUC(),
            )
        )
        client = TestClient(app)

        response = client.post(
            "/videos/00000000-0000-4000-8000-000000000001/collections/00000000-0000-4000-8000-000000000002/clips/00000000-0000-4000-8000-000000000003/export"
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], CLIP_EXPORT_FAILED)


if __name__ == "__main__":
    unittest.main()
