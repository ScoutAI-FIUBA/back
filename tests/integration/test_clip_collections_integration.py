from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from src.infrastructure.clip_collections.ffmpeg_clip_exporter import FFmpegClipExporter
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
        Path("src/infrastructure/players/migrations"),
        Path("src/infrastructure/team/migrations"),
        Path("src/infrastructure/matches/migrations"),
        Path("src/infrastructure/video/migrations"),
        Path("src/infrastructure/clip_collections/migrations"),
        Path("src/infrastructure/ownership/migrations"),
    ]
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for migration_dir in migration_dirs:
                for migration_file in sorted(migration_dir.glob("*.sql")):
                    cur.execute(migration_file.read_text(encoding="utf-8"))
        conn.commit()


def _seed_video_ownership_prerequisites(conn: psycopg.Connection) -> tuple[str, str, str]:
    user_id = f"user-{uuid4().hex[:8]}"
    team_id = str(uuid4())
    video_id = str(uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (id, email_normalized, password_hash, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            """,
            (user_id, f"{user_id}@example.com", "hash"),
        )
        cur.execute(
            """
            INSERT INTO teams (id, name, short_name, city, country, owner_user_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (team_id, f"Team {team_id[:8]}", f"T{team_id[:4]}", "Buenos Aires", "Argentina", user_id),
        )
        cur.execute(
            """
            INSERT INTO videos (
                id, team_id, owner_user_id, storage_key, title, status,
                duration_ms, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, 'READY', %s, NOW(), NOW())
            """,
            (video_id, team_id, user_id, f"videos/{video_id}.mp4", "Legacy source", 60_000),
        )
    return user_id, team_id, video_id


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
    monkeypatch.setattr(R2Storage, "generate_download_url", lambda self, key, expires_in=3600: f"https://download.local/{key}?exp={expires_in}")
    monkeypatch.setattr(R2Storage, "delete_video", lambda self, key: None)
    monkeypatch.setattr(R2Storage, "abort_multipart_upload", lambda self, key, upload_id: None)
    exported: list[tuple[str, str, int, int]] = []
    cached_exports: set[str] = set()
    monkeypatch.setattr(FFmpegClipExporter, "export_exists", lambda self, export_key: export_key in cached_exports)
    monkeypatch.setattr(
        FFmpegClipExporter,
        "export_clip",
        lambda self, source_key, export_key, start_ms, end_ms: (exported.append((source_key, export_key, start_ms, end_ms)), cached_exports.add(export_key)),
    )
    monkeypatch.setattr(FFmpegClipExporter, "generate_download_url", lambda self, export_key, expires_in=3600: f"https://download.local/{export_key}?exp={expires_in}")

    stack = ExitStack()

    def _build_client() -> tuple[TestClient, list[tuple[str, str, int, int]], set[str]]:
        app = create_app()
        test_client = stack.enter_context(TestClient(app))
        email = f"clips-{uuid4().hex}@example.com"
        password = "supersecret123"
        assert test_client.post("/auth/register", json={"email": email, "password": password}).status_code == 200
        login = test_client.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200
        test_client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
        return test_client, exported, cached_exports

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
        json={"team_id": team_id, "size_bytes": 123, "duration_ms": 60000, "upload_id": init.json()["upload_id"], "parts": [{"part_number": 1, "etag": "etag-1"}]},
    )
    assert complete.status_code == 200
    return team_id, video_id


def test_clip_collections_happy_path_single_batch_and_delete(client_factory) -> None:
    client, exported, cached_exports = client_factory()
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
        json={"start_ms": 1000, "end_ms": 5000, "description": "Opening play"},
    )
    assert single.status_code == 201
    first_item = single.json()["item"]
    assert first_item["start_ms"] == 1000
    assert first_item["end_ms"] == 5000
    assert first_item["description"] == "Opening play"

    batch = client.post(
        f"/videos/{video_id}/collections/{collection_id}/clips/batch",
        json={
            "clips": [
                {"start_ms": 5000, "end_ms": 9000},
                {"start_ms": 9000, "end_ms": 12000, "description": "Final shot"},
            ]
        },
    )
    assert batch.status_code == 201
    assert len(batch.json()["items"]) == 2

    detail = client.get(f"/videos/{video_id}/collections/{collection_id}")
    assert detail.status_code == 200
    assert [item["position"] for item in detail.json()["items"]] == [1, 2, 3]
    assert detail.json()["items"][0]["start_ms"] == 1000
    assert [item["description"] for item in detail.json()["items"]] == ["Opening play", None, "Final shot"]

    updated = client.patch(
        f"/videos/{video_id}/collections/{collection_id}/clips/{first_item['id']}",
        json={"description": "Renamed clip"},
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["description"] == "Renamed clip"

    cleared = client.patch(
        f"/videos/{video_id}/collections/{collection_id}/clips/{first_item['id']}",
        json={"description": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["item"]["description"] is None

    too_long = client.patch(
        f"/videos/{video_id}/collections/{collection_id}/clips/{first_item['id']}",
        json={"description": "x" * 201},
    )
    assert too_long.status_code == 422

    missing_item = client.patch(
        f"/videos/{video_id}/collections/{collection_id}/clips/00000000-0000-4000-8000-000000000000",
        json={"description": "Label"},
    )
    assert missing_item.status_code == 404

    export_response = client.post(f"/videos/{video_id}/collections/{collection_id}/clips/{first_item['id']}/export")
    assert export_response.status_code == 200
    assert export_response.json()["download_url"] == f"https://download.local/exports/{first_item['id']}.mp4?exp=3600"
    assert len(exported) == 1
    source_key, export_key, start_ms, end_ms = exported[0]
    assert source_key.startswith("videos/")
    assert export_key == f"exports/{first_item['id']}.mp4"
    assert (start_ms, end_ms) == (1000, 5000)
    assert export_key in cached_exports

    export_again = client.post(f"/videos/{video_id}/collections/{collection_id}/clips/{first_item['id']}/export")
    assert export_again.status_code == 200
    assert len(exported) == 1

    deleted = client.delete(f"/videos/{video_id}/collections/{collection_id}/clips/{first_item['id']}")
    assert deleted.status_code == 204

    detail_after_delete = client.get(f"/videos/{video_id}/collections/{collection_id}")
    assert detail_after_delete.status_code == 200
    assert len(detail_after_delete.json()["items"]) == 2


def test_clip_collection_migration_converges_legacy_schema_once_and_stays_stable() -> None:
    env = _required_env()
    try:
        with psycopg.connect(env["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS clip_collection_items")
                cur.execute("DROP TABLE IF EXISTS clip_collections")
                cur.execute(
                    """
                    CREATE TABLE clip_collections (
                        id UUID PRIMARY KEY,
                        video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                        team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                        owner_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        name VARCHAR(180) NOT NULL,
                        description TEXT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE clip_collection_items (
                        id UUID PRIMARY KEY,
                        collection_id UUID NOT NULL REFERENCES clip_collections(id) ON DELETE CASCADE,
                        filename VARCHAR(255) NOT NULL,
                        storage_key TEXT NOT NULL,
                        cloudflare_url TEXT NOT NULL,
                        position INTEGER NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE (collection_id, position)
                    )
                    """
                )
            conn.commit()

            _apply_migrations(env["DATABASE_URL"])

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = CURRENT_SCHEMA()
                      AND table_name = 'clip_collection_items'
                    ORDER BY ordinal_position
                    """
                )
                columns = [row[0] for row in cur.fetchall()]
                assert "start_ms" in columns
                assert "end_ms" in columns
                assert "description" in columns
                assert "filename" not in columns
                assert "storage_key" not in columns
                assert "cloudflare_url" not in columns

                user_id, team_id, video_id = _seed_video_ownership_prerequisites(conn)
                collection_id = str(uuid4())
                item_id = str(uuid4())
                cur.execute(
                    """
                    INSERT INTO clip_collections (
                        id, video_id, team_id, owner_user_id, name, description, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """,
                    (collection_id, video_id, team_id, user_id, "After convergence", None),
                )
                cur.execute(
                    """
                    INSERT INTO clip_collection_items (
                        id, collection_id, start_ms, end_ms, position, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    """,
                    (item_id, collection_id, 1_000, 5_000, 1),
                )
            conn.commit()

            _apply_migrations(env["DATABASE_URL"])

            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM clip_collection_items")
                assert cur.fetchone()[0] == 1
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable for integration tests: {exc}")


def test_clip_collections_are_private_to_video_owner(client_factory) -> None:
    owner_client, _, _ = client_factory()
    _, video_id = _create_ready_video(owner_client)
    created = owner_client.post(f"/videos/{video_id}/collections", json={"name": "Private"})
    assert created.status_code == 201
    collection_id = created.json()["collection"]["id"]

    other_client, _, _ = client_factory()

    for response in (
        other_client.get(f"/videos/{video_id}/collections"),
        other_client.get(f"/videos/{video_id}/collections/{collection_id}"),
        other_client.post(
            f"/videos/{video_id}/collections/{collection_id}/clips",
            json={"start_ms": 1000, "end_ms": 3000},
        ),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN_TEAM_ACCESS"
