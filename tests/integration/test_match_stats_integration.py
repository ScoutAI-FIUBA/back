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
        Path("src/infrastructure/jobs/migrations"),
        Path("src/infrastructure/ownership/migrations"),
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
            cur.execute("TRUNCATE TABLE match_participants RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE matches RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE players RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE teams RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE auth_refresh_sessions RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE users RESTART IDENTITY CASCADE")
        conn.commit()


@pytest.fixture
def client() -> TestClient:
    from src.interfaces.http.main import create_app

    env = _required_env()
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    app = create_app()
    with TestClient(app) as test_client:
        email = f"match-stats-{uuid4().hex}@example.com"
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


def _team_payload(name: str) -> dict[str, str]:
    return {"name": name, "short_name": name[:3].upper(), "city": "Buenos Aires", "country": "Argentina"}


def _player_payload(last_name: str) -> dict[str, object]:
    return {
        "first_name": "Player",
        "last_name": last_name,
        "birth_date": "1999-01-01",
        "height_cm": 190,
        "weight_kg": 85,
        "primary_position": "PG",
    }


def test_match_stats_foundation_flow(client: TestClient) -> None:
    home_team_id = client.post("/teams", json=_team_payload("Home Team")).json()["team"]["id"]
    away_team_id = client.post("/teams", json=_team_payload("Away Team")).json()["team"]["id"]

    player_response = client.post("/players", json=_player_payload(f"{uuid4().hex[:6]}"))
    assert player_response.status_code == 201
    player = player_response.json()["player"]

    player_stats = client.get(f"/players/{player['id']}/stats")
    assert player_stats.status_code == 200
    assert player_stats.json()["player"]["stats"]["games_played"] == 0

    created_match = client.post(
        "/matches",
        json={
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "match_date": "2024-04-20",
            "description": "League night",
        },
    )
    assert created_match.status_code == 201
    match_id = created_match.json()["match"]["id"]
    assert created_match.json()["match"]["winner_team_id"] is None

    listed = client.get("/matches")
    assert listed.status_code == 200
    assert len(listed.json()["matches"]) == 1

    filtered = client.get("/matches", params={"team_id": home_team_id})
    assert filtered.status_code == 200
    assert filtered.json()["matches"][0]["id"] == match_id

    replaced_stats = client.put(
        f"/matches/{match_id}/stats",
        json={
            "stats": {"scoreboard": {"home": 80, "away": 72}, "opaque": [1, 2, 3]},
            "winner_team_id": home_team_id,
            "participants": [
                {
                    "team_side": "HOME",
                    "display_name": "Player One",
                    "player_id": player["id"],
                    "jersey_number": "7",
                },
                {
                    "team_side": "AWAY",
                    "display_name": "External Player",
                    "jersey_number": "12",
                },
            ],
        },
    )
    assert replaced_stats.status_code == 200
    assert replaced_stats.json()["match"]["stats"]["scoreboard"]["home"] == 80
    assert len(replaced_stats.json()["participants"]) == 2

    fetched_stats = client.get(f"/matches/{match_id}/stats")
    assert fetched_stats.status_code == 200
    assert fetched_stats.json()["participants"][0]["player_id"] == player["id"]

    player_matches = client.get(f"/players/{player['id']}/matches")
    assert player_matches.status_code == 200
    assert player_matches.json()["matches"][0]["id"] == match_id

    team_stats = client.get(f"/teams/{home_team_id}/stats")
    assert team_stats.status_code == 200
    assert team_stats.json()["team"]["matches_played"] == 1
    assert team_stats.json()["team"]["wins"] == 1
    assert team_stats.json()["team"]["losses"] == 0
    assert team_stats.json()["team"]["results"][0]["result"] == "WIN"

    team_delete = client.delete(f"/teams/{home_team_id}")
    assert team_delete.status_code == 409
    assert team_delete.json()["error"]["code"] == "TEAM_HAS_MATCHES"
