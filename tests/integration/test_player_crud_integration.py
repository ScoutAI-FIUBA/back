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


def test_player_with_only_a_name_round_trips_with_nulls(client: TestClient) -> None:
    created = client.post("/players", json={"first_name": "Ana", "last_name": "Paz", "jersey_number": "7"})
    assert created.status_code == 201
    player_id = created.json()["player"]["id"]

    listed = client.get("/players").json()["players"]
    assert [p["id"] for p in listed] == [player_id]
    for key in ("birth_date", "height_cm", "weight_kg", "primary_position"):
        assert listed[0][key] is None

    filled = client.put(f"/players/{player_id}", json={**_payload(), "first_name": "Ana"})
    assert filled.status_code == 200
    cleared = client.put(f"/players/{player_id}", json={"first_name": "Ana", "last_name": "Paz"})
    assert cleared.status_code == 200
    assert cleared.json()["player"]["height_cm"] is None
    assert cleared.json()["player"]["birth_date"] is None


def test_bulk_roster_creates_and_skips_taken_jerseys(client: TestClient) -> None:
    team_id = client.post("/teams", json=_team_payload()).json()["team"]["id"]

    def entry(number: str) -> dict[str, str]:
        return {"first_name": f"P{number}", "last_name": f"Q{number}", "jersey_number": number}

    first = client.post("/players/bulk", json={"team_id": team_id, "players": [entry("7"), entry("10")]})
    assert first.status_code == 201
    assert [p["jersey_number"] for p in first.json()["created"]] == ["7", "10"]

    again = client.post("/players/bulk", json={"team_id": team_id, "players": [entry("7"), entry("11")]})
    assert again.status_code == 201
    assert [p["jersey_number"] for p in again.json()["created"]] == ["11"]
    assert again.json()["skipped"] == [{"jersey_number": "7", "reason": "jersey_taken"}]

    roster = client.get("/players", params={"team_id": team_id}).json()["players"]
    assert sorted(p["jersey_number"] for p in roster) == ["10", "11", "7"]

    missing_team = client.post("/players/bulk", json={"team_id": str(uuid4()), "players": [entry("1")]})
    assert missing_team.status_code == 404
    assert missing_team.json()["error"]["code"] == "TEAM_NOT_FOUND"
    assert len(client.get("/players").json()["players"]) == 3


def test_bulk_roster_is_all_or_nothing(client: TestClient) -> None:
    from src.application.players.use_cases import (
        CreateTeamRosterCommand,
        CreateTeamRosterUseCase,
        RosterPlayerInput,
    )
    from src.infrastructure.players.postgres_player_repository import PostgresPlayerRepository
    from src.infrastructure.team.postgres_repository import PostgresTeamRepository
    from src.interfaces.http.bootstrap.dependencies import OperationConnection, PsycopgUnitOfWork, UUIDIds

    team_id = client.post("/teams", json=_team_payload()).json()["team"]["id"]
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url) as conn:
        owner_id = str(conn.execute("SELECT owner_user_id FROM teams WHERE id = %s", (team_id,)).fetchone()[0])

    connection = OperationConnection(database_url)
    use_case = CreateTeamRosterUseCase(
        players=PostgresPlayerRepository(connection=connection),
        teams=PostgresTeamRepository(connection=connection),
        ids=UUIDIds(),
        uow=PsycopgUnitOfWork(connection),
    )
    # The second name does not fit VARCHAR(120): the first insert must roll back with it.
    with pytest.raises(psycopg.errors.StringDataRightTruncation):
        use_case.execute(
            CreateTeamRosterCommand(
                user_id=owner_id,
                team_id=team_id,
                players=[RosterPlayerInput("Ok", "Fine", "5"), RosterPlayerInput("X" * 121, "Long", "6")],
            )
        )
    assert client.get("/players", params={"team_id": team_id}).json()["players"] == []
