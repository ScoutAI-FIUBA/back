from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from src.interfaces.http.main import create_app


pytestmark = pytest.mark.integration


def _required_env() -> dict[str, str]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.fail("DATABASE_URL is required for integration tests")

    return {
        "DATABASE_URL": database_url,
        "AUTH_JWT_SECRET": "integration-jwt-secret",
        "AUTH_REFRESH_SECRET": "integration-refresh-secret",
        "AUTH_JWT_ISSUER": "scoutai-integration",
        "AUTH_JWT_AUDIENCE": "scoutai-integration-client",
    }


def _apply_migrations(database_url: str, migration_dir: Path) -> None:
    migration_files = sorted(migration_dir.glob("*.sql"))

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for migration_file in migration_files:
                cur.execute(migration_file.read_text(encoding="utf-8"))
        conn.commit()


@pytest.fixture(scope="session", autouse=True)
def _integration_schema_ready() -> None:
    env = _required_env()
    _apply_migrations(env["DATABASE_URL"], Path("src/infrastructure/auth/migrations"))
    _apply_migrations(env["DATABASE_URL"], Path("src/infrastructure/team/migrations"))


@pytest.fixture(autouse=True)
def _tables_clean() -> None:
    env = _required_env()
    with psycopg.connect(env["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE auth_refresh_sessions, users RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE teams RESTART IDENTITY CASCADE")
        conn.commit()


@pytest.fixture
def client() -> TestClient:
    env = _required_env()
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _payload(suffix: str) -> dict[str, str]:
    return {
        "name": f"Team {suffix}",
        "short_name": f"T{suffix[:4]}",
        "city": "Buenos Aires",
        "country": "Argentina",
    }


def test_team_crud_happy_path(client: TestClient) -> None:
    created = client.post("/teams", json=_payload(uuid4().hex))
    assert created.status_code == 201
    team = created.json()["team"]
    assert team["id"]
    assert team["name"].startswith("Team ")
    assert team["created_at"]

    listed = client.get("/teams")
    assert listed.status_code == 200
    assert len(listed.json()["teams"]) == 1

    updated = client.put(
        f"/teams/{team['id']}",
        json={"name": "Updated Team", "short_name": "UPD", "city": "Cordoba", "country": "Argentina"},
    )
    assert updated.status_code == 200
    assert updated.json()["team"]["name"] == "Updated Team"

    deleted = client.delete(f"/teams/{team['id']}")
    assert deleted.status_code == 204

    empty = client.get("/teams")
    assert empty.status_code == 200
    assert empty.json()["teams"] == []


def test_team_update_and_delete_not_found(client: TestClient) -> None:
    missing_id = str(uuid4())

    updated = client.put(
        f"/teams/{missing_id}",
        json={"name": "Updated Team", "short_name": "UPD", "city": "Cordoba", "country": "Argentina"},
    )
    assert updated.status_code == 404
    assert updated.json()["detail"] == "Team not found"

    deleted = client.delete(f"/teams/{missing_id}")
    assert deleted.status_code == 404
    assert deleted.json()["detail"] == "Team not found"


def test_team_validation_paths(client: TestClient) -> None:
    invalid_create = client.post("/teams", json={"name": "", "short_name": "", "city": "", "country": ""})
    assert invalid_create.status_code == 422

    invalid_id = client.put(
        "/teams/not-a-uuid",
        json={"name": "x", "short_name": "y", "city": "z", "country": "w"},
    )
    assert invalid_id.status_code == 422
