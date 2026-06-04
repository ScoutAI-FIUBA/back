from __future__ import annotations

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
def _video_tables_clean() -> None:
    env = _required_env()
    try:
        with psycopg.connect(env["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE video_players RESTART IDENTITY CASCADE")
                cur.execute("TRUNCATE TABLE videos RESTART IDENTITY CASCADE")
                cur.execute("TRUNCATE TABLE players RESTART IDENTITY CASCADE")
                cur.execute("TRUNCATE TABLE teams RESTART IDENTITY CASCADE")
            conn.commit()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable for integration tests: {exc}")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from src.interfaces.http.main import create_app

    env = _required_env()
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)

    monkeypatch.setattr(
        R2Storage,
        "init_multipart_upload",
        lambda self, key, content_type=None: "upload-it-1",
    )
    monkeypatch.setattr(
        R2Storage,
        "generate_presigned_upload_part_url",
        lambda self, key, upload_id, part_number, expires_in=900: f"https://upload.local/{key}/{upload_id}/{part_number}",
    )
    monkeypatch.setattr(
        R2Storage,
        "complete_multipart_upload",
        lambda self, key, upload_id, parts: "etag-final",
    )
    monkeypatch.setattr(
        R2Storage,
        "generate_presigned_url",
        lambda self, key, expires_in=900: f"https://play.local/{key}?exp={expires_in}",
    )
    monkeypatch.setattr(R2Storage, "delete_video", lambda self, key: None)
    monkeypatch.setattr(R2Storage, "abort_multipart_upload", lambda self, key, upload_id: None)

    app = create_app()
    with TestClient(app) as test_client:
        email = f"videos-{uuid4().hex}@example.com"
        password = "supersecret123"
        register = test_client.post("/auth/register", json={"email": email, "password": password})
        assert register.status_code == 200
        login = test_client.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200
        test_client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
        yield test_client

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


def _player_payload() -> dict[str, object]:
    return {
        "first_name": "Lio",
        "last_name": f"Messi-{uuid4().hex[:8]}",
        "birth_date": "1987-06-24",
        "height_cm": 170,
        "weight_kg": 72,
        "primary_position": "RW",
    }


def test_video_players_replace_integrity_and_delete_visibility(client: TestClient) -> None:
    team_response = client.post("/teams", json=_team_payload())
    assert team_response.status_code == 201
    team_id = team_response.json()["team"]["id"]

    p1 = client.post("/players", json=_player_payload())
    p2 = client.post("/players", json=_player_payload())
    assert p1.status_code == 201 and p2.status_code == 201
    p1_id = p1.json()["player"]["id"]
    p2_id = p2.json()["player"]["id"]
    assert client.put(f"/players/{p1_id}/team/{team_id}").status_code == 200
    assert client.put(f"/players/{p2_id}/team/{team_id}").status_code == 200

    init = client.post("/videos/upload/init", json={"team_id": team_id, "title": "Clip"})
    assert init.status_code == 201
    video_id = init.json()["video_id"]
    upload_id = init.json()["upload_id"]

    complete = client.post(
        f"/videos/{video_id}/upload/complete",
        json={
            "team_id": team_id,
            "size_bytes": 123,
            "upload_id": upload_id,
            "parts": [{"part_number": 1, "etag": "etag-1"}],
        },
    )
    assert complete.status_code == 200

    update = client.patch(
        f"/videos/{video_id}",
        json={"team_id": team_id, "player_ids": [p1_id, p2_id]},
    )
    assert update.status_code == 200

    replace = client.patch(
        f"/videos/{video_id}",
        json={"team_id": team_id, "player_ids": [p2_id]},
    )
    assert replace.status_code == 200

    db_url = os.environ["DATABASE_URL"]
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT player_id::text FROM video_players WHERE video_id = %s::uuid ORDER BY player_id::text",
                (video_id,),
            )
            rows = [row[0] for row in cur.fetchall()]
    assert rows == [p2_id]

    deleted = client.delete(f"/videos/{video_id}", params={"team_id": team_id})
    assert deleted.status_code == 204

    listed = client.get("/videos", params={"team_id": team_id})
    assert listed.status_code == 200
    assert listed.json()["videos"] == []


def test_video_update_rejects_cross_team_player(client: TestClient) -> None:
    team_a = client.post("/teams", json=_team_payload())
    team_b = client.post("/teams", json=_team_payload())
    assert team_a.status_code == 201 and team_b.status_code == 201
    team_a_id = team_a.json()["team"]["id"]
    team_b_id = team_b.json()["team"]["id"]

    player = client.post("/players", json=_player_payload())
    assert player.status_code == 201
    player_id = player.json()["player"]["id"]
    assert client.put(f"/players/{player_id}/team/{team_b_id}").status_code == 200

    init = client.post("/videos/upload/init", json={"team_id": team_a_id, "title": "Clip"})
    assert init.status_code == 201
    video_id = init.json()["video_id"]
    assert (
        client.post(
            f"/videos/{video_id}/upload/complete",
            json={
                "team_id": team_a_id,
                "size_bytes": 200,
                "upload_id": init.json()["upload_id"],
                "parts": [{"part_number": 1, "etag": "etag-1"}],
            },
        ).status_code
        == 200
    )

    update = client.patch(
        f"/videos/{video_id}",
        json={"team_id": team_a_id, "player_ids": [player_id]},
    )
    assert update.status_code == 422
    assert update.json()["error"]["code"] == "PLAYER_TEAM_MISMATCH"


def test_upload_init_unknown_team_returns_404_and_does_not_create_video(client: TestClient) -> None:
    missing_team_id = str(uuid4())

    response = client.post(
        "/videos/upload/init",
        json={"team_id": missing_team_id, "title": "No team"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TEAM_NOT_FOUND"

    db_url = os.environ["DATABASE_URL"]
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM videos")
            count = cur.fetchone()[0]
    assert count == 0
