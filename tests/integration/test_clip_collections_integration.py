from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from src.infrastructure.storage import R2Storage


pytestmark = pytest.mark.integration


def _required_env() -> dict[str, str]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for integration tests")
    return {
        "DATABASE_URL": database_url,
        "AUTH_JWT_SECRET": "integration-jwt-secret",
        "AUTH_REFRESH_SECRET": "integration-refresh-secret",
        "AUTH_JWT_ISSUER": "scoutai-integration",
        "AUTH_JWT_AUDIENCE": "scoutai-integration-client",
    }


def _apply_migrations(database_url: str) -> None:
    migration_dirs = [
        Path("src/infrastructure/auth/migrations"),
        Path("src/infrastructure/team/migrations"),
        Path("src/infrastructure/video/migrations"),
        Path("src/infrastructure/clip_collections/migrations"),
    ]
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for migration_dir in migration_dirs:
                for migration_file in sorted(migration_dir.glob("*.sql")):
                    cur.execute(migration_file.read_text(encoding="utf-8"))
        conn.commit()


@pytest.fixture(scope="session", autouse=True)
def _integration_schema_ready() -> None:
    env = _required_env()
    try:
        _apply_migrations(env["DATABASE_URL"])
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable for integration tests: {exc}")


@pytest.fixture(autouse=True)
def _tables_clean() -> None:
    env = _required_env()
    with psycopg.connect(env["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE clip_collection_items RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE clip_collections RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE video_players RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE videos RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE players RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE teams RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE auth_refresh_sessions, users RESTART IDENTITY CASCADE")
        conn.commit()


@pytest.fixture
def client_factory(monkeypatch: pytest.MonkeyPatch):
    from src.interfaces.http.main import create_app

    env = _required_env()
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)

    monkeypatch.setattr(R2Storage, "init_multipart_upload", lambda self, key, content_type=None: "upload-it-1")
    monkeypatch.setattr(
        R2Storage,
        "generate_presigned_upload_part_url",
        lambda self, key, upload_id, part_number, expires_in=900: f"https://upload.local/{key}/{upload_id}/{part_number}",
    )
    monkeypatch.setattr(R2Storage, "complete_multipart_upload", lambda self, key, upload_id, parts: "etag-final")
    monkeypatch.setattr(R2Storage, "generate_presigned_url", lambda self, key, expires_in=900: f"https://play.local/{key}?exp={expires_in}")
    monkeypatch.setattr(R2Storage, "delete_video", lambda self, key: None)
    monkeypatch.setattr(R2Storage, "abort_multipart_upload", lambda self, key, upload_id: None)

    stack = ExitStack()

    def _build_client() -> TestClient:
        app = create_app()
        test_client = stack.enter_context(TestClient(app))
        email = f"clips-{uuid4().hex}@example.com"
        password = "supersecret123"
        assert test_client.post("/auth/register", json={"email": email, "password": password}).status_code == 200
        login = test_client.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200
        test_client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
        return test_client

    try:
        yield _build_client
    finally:
        stack.close()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _team_payload() -> dict[str, str]:
    suffix = uuid4().hex[:8]
    return {
        "name": f"Team {suffix}",
        "short_name": f"T{suffix[:4]}",
        "city": "Buenos Aires",
        "country": "Argentina",
    }


def _create_ready_video(client: TestClient) -> tuple[str, str]:
    team_response = client.post("/teams", json=_team_payload())
    assert team_response.status_code == 201
    team_id = team_response.json()["team"]["id"]
    init = client.post("/videos/upload/init", json={"team_id": team_id, "title": "Match clip source"})
    assert init.status_code == 201
    video_id = init.json()["video_id"]
    complete = client.post(
        f"/videos/{video_id}/upload/complete",
        json={"team_id": team_id, "size_bytes": 123, "upload_id": init.json()["upload_id"], "parts": [{"part_number": 1, "etag": "etag-1"}]},
    )
    assert complete.status_code == 200
    return team_id, video_id


def test_clip_collections_happy_path_single_batch_and_delete(client_factory) -> None:
    client = client_factory()
    _, video_id = _create_ready_video(client)

    created = client.post(f"/videos/{video_id}/collections", json={"name": "Highlights", "description": "First cut"})
    assert created.status_code == 201
    collection = created.json()["collection"]
    collection_id = collection["id"]

    listed = client.get(f"/videos/{video_id}/collections")
    assert listed.status_code == 200
    assert [entry["id"] for entry in listed.json()["collections"]] == [collection_id]

    single = client.post(
        f"/videos/{video_id}/collections/{collection_id}/clips",
        json={"filename": "goal 1.mp4", "cloudflare_url": "https://cdn.local/goal-1.mp4"},
    )
    assert single.status_code == 201
    first_item = single.json()["item"]
    assert first_item["storage_key"].startswith("user/")
    assert f"/video/{video_id}/collection/{collection_id}/clips/" in first_item["storage_key"]

    batch = client.post(
        f"/videos/{video_id}/collections/{collection_id}/clips/batch",
        json={
            "clips": [
                {"filename": "goal 2.mp4", "cloudflare_url": "https://cdn.local/goal-2.mp4"},
                {"filename": "assist.mov", "cloudflare_url": "https://cdn.local/assist.mov"},
            ]
        },
    )
    assert batch.status_code == 201
    assert len(batch.json()["items"]) == 2

    detail = client.get(f"/videos/{video_id}/collections/{collection_id}")
    assert detail.status_code == 200
    assert [item["position"] for item in detail.json()["items"]] == [1, 2, 3]

    deleted = client.delete(f"/videos/{video_id}/collections/{collection_id}/clips/{first_item['id']}")
    assert deleted.status_code == 204

    detail_after_delete = client.get(f"/videos/{video_id}/collections/{collection_id}")
    assert detail_after_delete.status_code == 200
    assert len(detail_after_delete.json()["items"]) == 2


def test_clip_collections_are_private_to_video_owner(client_factory) -> None:
    owner_client = client_factory()
    _, video_id = _create_ready_video(owner_client)
    created = owner_client.post(f"/videos/{video_id}/collections", json={"name": "Private"})
    assert created.status_code == 201
    collection_id = created.json()["collection"]["id"]

    other_client = client_factory()

    for response in (
        other_client.get(f"/videos/{video_id}/collections"),
        other_client.get(f"/videos/{video_id}/collections/{collection_id}"),
        other_client.post(
            f"/videos/{video_id}/collections/{collection_id}/clips",
            json={"filename": "steal.mp4", "cloudflare_url": "https://cdn.local/steal.mp4"},
        ),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN_TEAM_ACCESS"
