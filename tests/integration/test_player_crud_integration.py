from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest


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


def _apply_migrations(database_url: str) -> None:
    migration_dirs = [
        Path("src/infrastructure/auth/migrations"),
        Path("src/infrastructure/players/migrations"),
        Path("src/infrastructure/team/migrations"),
        Path("src/infrastructure/matches/migrations"),
    ]
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for migration_dir in migration_dirs:
                for migration_file in sorted(migration_dir.glob("*.sql")):
                    sql = migration_file.read_text(encoding="utf-8")
                    cur.execute(sql)
        conn.commit()


@pytest.fixture(scope="session", autouse=True)
def _integration_schema_ready() -> None:
    env = _required_env()
    try:
        _apply_migrations(env["DATABASE_URL"])
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable for integration tests: {exc}")


@pytest.fixture(autouse=True)
def _players_table_clean() -> None:
    env = _required_env()
    try:
        with psycopg.connect(env["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE players RESTART IDENTITY CASCADE")
                cur.execute("TRUNCATE TABLE teams RESTART IDENTITY CASCADE")
            conn.commit()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable for integration tests: {exc}")


@pytest.fixture
def client() -> TestClient:
    from src.interfaces.http.main import create_app

    env = _required_env()
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    app = create_app()
    with TestClient(app) as test_client:
        email = f"players-{uuid4().hex}@example.com"
        password = "supersecret123"
        register = test_client.post("/auth/register", json={"email": email, "password": password})
        assert register.status_code == 200

        login = test_client.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200
        access_token = login.json()["access_token"]
        test_client.headers.update({"Authorization": f"Bearer {access_token}"})
        yield test_client
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _payload() -> dict[str, object]:
    return {
        "first_name": "Lionel",
        "last_name": f"Messi-{uuid4().hex[:8]}",
        "birth_date": "1987-06-24",
        "height_cm": 170,
        "weight_kg": 72,
        "primary_position": "SF",
    }


def _team_payload() -> dict[str, str]:
    suffix = uuid4().hex[:8]
    return {
        "name": f"Team {suffix}",
        "short_name": f"T{suffix[:4]}",
        "city": "Buenos Aires",
        "country": "Argentina",
    }


def test_player_crud_happy_path(client: TestClient) -> None:
    created = client.post("/players", json=_payload())
    assert created.status_code == 201
    player = created.json()["player"]
    player_id = player["id"]

    listed = client.get("/players")
    assert listed.status_code == 200
    assert len(listed.json()["players"]) == 1
    assert listed.json()["players"][0]["id"] == player_id

    updated = client.put(
        f"/players/{player_id}",
        json={
            "first_name": "Leo",
            "last_name": player["last_name"],
            "birth_date": "1987-06-24",
            "height_cm": 171,
            "weight_kg": 73,
            "primary_position": "PG",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["player"]["first_name"] == "Leo"
    assert updated.json()["player"]["height_cm"] == 171

    deleted = client.delete(f"/players/{player_id}")
    assert deleted.status_code == 204

    listed_after_delete = client.get("/players")
    assert listed_after_delete.status_code == 200
    assert listed_after_delete.json()["players"] == []


def test_jersey_number_persists_across_reads_and_updates(client: TestClient) -> None:
    created = client.post("/players", json={**_payload(), "jersey_number": "0"})
    assert created.status_code == 201
    player = created.json()["player"]
    assert player["jersey_number"] == "0"
    player_id = player["id"]

    listed = client.get("/players")
    assert listed.json()["players"][0]["jersey_number"] == "0"

    updated = client.put(
        f"/players/{player_id}",
        json={
            "first_name": player["first_name"],
            "last_name": player["last_name"],
            "birth_date": player["birth_date"],
            "height_cm": player["height_cm"],
            "weight_kg": player["weight_kg"],
            "primary_position": player["primary_position"],
            "jersey_number": "00",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["player"]["jersey_number"] == "00"

    reread = client.get("/players")
    assert reread.json()["players"][0]["jersey_number"] == "00"


def test_player_update_and_delete_return_404_when_player_missing(client: TestClient) -> None:
    missing_id = str(uuid4())
    update_missing = client.put(
        f"/players/{missing_id}",
        json={
            "first_name": "A",
            "last_name": "B",
            "birth_date": "1990-01-01",
            "height_cm": 180,
            "weight_kg": 75,
            "primary_position": "PF",
        },
    )
    assert update_missing.status_code == 404
    assert update_missing.json()["error"]["code"] == "PLAYER_NOT_FOUND"

    delete_missing = client.delete(f"/players/{missing_id}")
    assert delete_missing.status_code == 404
    assert delete_missing.json()["error"]["code"] == "PLAYER_NOT_FOUND"


def test_player_request_validation_contract(client: TestClient) -> None:
    invalid = client.post(
        "/players",
        json={
            "first_name": "",
            "last_name": "",
            "birth_date": "not-a-date",
            "height_cm": -1,
            "weight_kg": 0,
            "primary_position": "",
        },
    )
    assert invalid.status_code == 422


def test_assign_player_to_team_persists_and_can_be_queried_by_team(client: TestClient) -> None:
    created_team = client.post("/teams", json=_team_payload())
    assert created_team.status_code == 201
    team_id = created_team.json()["team"]["id"]

    created_player = client.post("/players", json=_payload())
    assert created_player.status_code == 201
    player_id = created_player.json()["player"]["id"]

    assigned = client.put(f"/players/{player_id}/team/{team_id}")
    assert assigned.status_code == 200
    assert assigned.json()["player"]["team_id"] == team_id

    filtered = client.get("/players", params={"team_id": team_id})
    assert filtered.status_code == 200
    assert len(filtered.json()["players"]) == 1
    assert filtered.json()["players"][0]["id"] == player_id
    assert filtered.json()["players"][0]["team_id"] == team_id


def test_player_update_preserves_assigned_team(client: TestClient) -> None:
    created_team = client.post("/teams", json=_team_payload())
    assert created_team.status_code == 201
    team_id = created_team.json()["team"]["id"]

    created_player = client.post("/players", json=_payload())
    assert created_player.status_code == 201
    player = created_player.json()["player"]
    player_id = player["id"]

    assigned = client.put(f"/players/{player_id}/team/{team_id}")
    assert assigned.status_code == 200
    assert assigned.json()["player"]["team_id"] == team_id

    updated = client.put(
        f"/players/{player_id}",
        json={
            "first_name": "Leo",
            "last_name": player["last_name"],
            "birth_date": "1987-06-24",
            "height_cm": 171,
            "weight_kg": 73,
            "primary_position": "PG",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["player"]["team_id"] == team_id


def test_assign_player_to_missing_team_returns_404(client: TestClient) -> None:
    created_player = client.post("/players", json=_payload())
    assert created_player.status_code == 201
    player_id = created_player.json()["player"]["id"]

    assign_missing_team = client.put(f"/players/{player_id}/team/{uuid4()}")
    assert assign_missing_team.status_code == 404
    assert assign_missing_team.json()["error"]["code"] == "TEAM_NOT_FOUND"


def test_deleting_team_keeps_player_and_clears_team_relation(client: TestClient) -> None:
    created_team = client.post("/teams", json=_team_payload())
    assert created_team.status_code == 201
    team_id = created_team.json()["team"]["id"]

    created_player = client.post("/players", json=_payload())
    assert created_player.status_code == 201
    player_id = created_player.json()["player"]["id"]

    assigned = client.put(f"/players/{player_id}/team/{team_id}")
    assert assigned.status_code == 200
    assert assigned.json()["player"]["team_id"] == team_id

    deleted_team = client.delete(f"/teams/{team_id}")
    assert deleted_team.status_code == 204

    players = client.get("/players")
    assert players.status_code == 200
    assert len(players.json()["players"]) == 1
    assert players.json()["players"][0]["id"] == player_id
    assert players.json()["players"][0]["team_id"] is None

    filtered = client.get("/players", params={"team_id": team_id})
    assert filtered.status_code == 200
    assert filtered.json()["players"] == []


def test_deleting_player_does_not_delete_team(client: TestClient) -> None:
    created_team = client.post("/teams", json=_team_payload())
    assert created_team.status_code == 201
    team_id = created_team.json()["team"]["id"]

    created_player = client.post("/players", json=_payload())
    assert created_player.status_code == 201
    player_id = created_player.json()["player"]["id"]

    assigned = client.put(f"/players/{player_id}/team/{team_id}")
    assert assigned.status_code == 200

    deleted_player = client.delete(f"/players/{player_id}")
    assert deleted_player.status_code == 204

    teams = client.get("/teams")
    assert teams.status_code == 200
    assert len(teams.json()["teams"]) == 1
    assert teams.json()["teams"][0]["id"] == team_id

    filtered = client.get("/players", params={"team_id": team_id})
    assert filtered.status_code == 200
    assert filtered.json()["players"] == []
