from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from src.infrastructure.storage import R2Storage


pytestmark = pytest.mark.integration

MIGRATION_DIRS = [
    Path("src/infrastructure/auth/migrations"),
    Path("src/infrastructure/players/migrations"),
    Path("src/infrastructure/team/migrations"),
    Path("src/infrastructure/matches/migrations"),
    Path("src/infrastructure/video/migrations"),
    Path("src/infrastructure/jobs/migrations"),
    Path("src/infrastructure/ownership/migrations"),
]
LINK_MIGRATION = Path("src/infrastructure/video/migrations/004_video_match_link.sql")


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
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for migration_dir in MIGRATION_DIRS:
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
            cur.execute("TRUNCATE TABLE users RESTART IDENTITY CASCADE")
            cur.execute("TRUNCATE TABLE teams RESTART IDENTITY CASCADE")
        conn.commit()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from src.interfaces.http.main import create_app

    env = _required_env()
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    monkeypatch.setattr(R2Storage, "init_multipart_upload", lambda self, key, content_type=None: "upload-it-1")
    monkeypatch.setattr(
        R2Storage,
        "generate_presigned_upload_part_url",
        lambda self, key, upload_id, part_number, expires_in=900: f"https://upload.local/{key}/{part_number}",
    )
    monkeypatch.setattr(R2Storage, "complete_multipart_upload", lambda self, key, upload_id, parts: "etag-final")
    monkeypatch.setattr(
        R2Storage, "generate_presigned_url", lambda self, key, expires_in=900: f"https://play.local/{key}"
    )
    monkeypatch.setattr(R2Storage, "delete_video", lambda self, key: None)
    app = create_app()
    with TestClient(app) as test_client:
        test_client.headers.update(_login(test_client))
        yield test_client
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _login(client: TestClient) -> dict[str, str]:
    email = f"link-{uuid4().hex}@example.com"
    password = "supersecret123"
    assert client.post("/auth/register", json={"email": email, "password": password}).status_code == 200
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _team(client: TestClient, name: str, headers: dict | None = None) -> str:
    response = client.post(
        "/teams",
        json={"name": f"{name} {uuid4().hex[:6]}", "short_name": name[:3].upper(), "city": "BA", "country": "AR"},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["team"]["id"]


def _video(client: TestClient, team_id: str) -> str:
    init = client.post("/videos/upload/init", json={"team_id": team_id, "title": "Clip"})
    assert init.status_code == 201
    video_id = init.json()["video_id"]
    done = client.post(
        f"/videos/{video_id}/upload/complete",
        json={
            "team_id": team_id,
            "size_bytes": 10,
            "upload_id": init.json()["upload_id"],
            "parts": [{"part_number": 1, "etag": "e"}],
        },
    )
    assert done.status_code == 200
    assert done.json()["video"]["match_id"] is None
    return video_id


def _match(client: TestClient, home: str, away: str, headers: dict | None = None) -> str:
    response = client.post(
        "/matches",
        json={"home_team_id": home, "away_team_id": away, "match_date": "2024-04-20", "description": "d"},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["match"]["id"]


def _put(client: TestClient, video_id: str, team_id: str, match_id: str | None):
    return client.put(f"/videos/{video_id}/match", json={"team_id": team_id, "match_id": match_id})


def _db_scalar(sql: str, params: tuple = ()):
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0]


def test_link_flow_over_real_postgres(client: TestClient) -> None:
    home, away, third = _team(client, "Home"), _team(client, "Away"), _team(client, "Third")
    match_id = _match(client, home, away)
    other_match_id = _match(client, home, third)
    v_home, v_away, v_third = _video(client, home), _video(client, away), _video(client, third)

    # Several videos of one match, home and away side.
    for video_id, team_id in ((v_home, home), (v_away, away)):
        response = _put(client, video_id, team_id, match_id)
        assert response.status_code == 200
        assert response.json()["video"]["match_id"] == match_id
    assert _db_scalar("SELECT COUNT(*) FROM videos WHERE match_id = %s::uuid", (match_id,)) == 2

    # match_id is exposed by list and get.
    listed = client.get("/videos", params={"team_id": home}).json()["videos"]
    assert [v["match_id"] for v in listed] == [match_id]
    got = client.get(f"/videos/{v_home}", params={"team_id": home}).json()["video"]
    assert got["match_id"] == match_id

    # updated_at is bumped by a link change.
    before = _db_scalar("SELECT updated_at FROM videos WHERE id = %s::uuid", (v_home,))
    assert _put(client, v_home, home, other_match_id).json()["video"]["match_id"] == other_match_id  # overwrite
    assert _db_scalar("SELECT updated_at FROM videos WHERE id = %s::uuid", (v_home,)) > before

    # Team not in the match -> 422, link unchanged.
    rejected = _put(client, v_third, third, match_id)
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "VIDEO_TEAM_NOT_IN_MATCH"
    assert _db_scalar("SELECT match_id FROM videos WHERE id = %s::uuid", (v_third,)) is None

    # Wrong team_id for the video -> 404; unknown match -> 404.
    assert _put(client, v_home, away, match_id).json()["error"]["code"] == "VIDEO_NOT_FOUND"
    unknown = _put(client, v_home, home, str(uuid4()))
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "MATCH_NOT_FOUND")

    # Clear.
    cleared = _put(client, v_home, home, None)
    assert cleared.status_code == 200 and cleared.json()["video"]["match_id"] is None
    assert _db_scalar("SELECT match_id FROM videos WHERE id = %s::uuid", (v_home,)) is None

    # Deleted video is rejected.
    assert client.delete(f"/videos/{v_away}", params={"team_id": away}).status_code == 204
    gone = _put(client, v_away, away, match_id)
    assert (gone.status_code, gone.json()["error"]["code"]) == (404, "VIDEO_NOT_FOUND")


def test_other_users_match_is_404_and_auth_is_required(client: TestClient) -> None:
    home, away = _team(client, "Home"), _team(client, "Away")
    video_id = _video(client, home)
    other_headers = _login(client)
    other_home, other_away = _team(client, "OHome", other_headers), _team(client, "OAway", other_headers)
    foreign_match = _match(client, other_home, other_away, other_headers)

    response = _put(client, video_id, home, foreign_match)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "MATCH_NOT_FOUND")
    assert _db_scalar("SELECT match_id FROM videos WHERE id = %s::uuid", (video_id,)) is None

    # Another user cannot touch my video either.
    mine = _match(client, home, away)
    intruder = client.put(
        f"/videos/{video_id}/match", json={"team_id": home, "match_id": mine}, headers=other_headers
    )
    assert intruder.status_code == 404

    # Unauthenticated, bad UUIDs.
    anon = TestClient(client.app)
    assert anon.put(f"/videos/{video_id}/match", json={"team_id": home, "match_id": mine}).status_code == 401
    assert anon.patch(f"/matches/{mine}", json={"description": "x"}).status_code == 401
    assert _put(client, video_id, home, "not-a-uuid").status_code == 422


def test_patch_match_over_real_postgres(client: TestClient) -> None:
    home, away = _team(client, "Home"), _team(client, "Away")
    match_id = _match(client, home, away)
    stats = {"opaque": True}
    assert client.put(f"/matches/{match_id}/stats", json={"stats": stats, "winner_team_id": home}).status_code == 200

    participants = [{"team_side": "HOME", "display_name": "Ana"}, {"team_side": "AWAY", "display_name": "Bea"}]
    assert client.put(
        f"/matches/{match_id}/stats", json={"stats": stats, "winner_team_id": home, "participants": participants}
    ).status_code == 200
    assert _db_scalar("SELECT COUNT(*) FROM match_participants WHERE match_id = %s::uuid", (match_id,)) == 2

    extra = client.patch(f"/matches/{match_id}", json={"home_team_id": away, "description": "nope"})
    assert extra.status_code == 422
    assert _db_scalar("SELECT description FROM matches WHERE id = %s::uuid", (match_id,)) == "d"

    patched = client.patch(f"/matches/{match_id}", json={"match_date": "2025-01-02", "description": "edited"})
    assert patched.status_code == 200
    match = patched.json()["match"]
    assert (match["match_date"], match["description"]) == ("2025-01-02", "edited")
    assert (match["home_team_id"], match["away_team_id"], match["winner_team_id"], match["stats"]) == (
        home, away, home, stats,
    )

    assert _db_scalar("SELECT COUNT(*) FROM match_participants WHERE match_id = %s::uuid", (match_id,)) == 2
    assert _db_scalar("SELECT home_team_id::text FROM matches WHERE id = %s::uuid", (match_id,)) == home
    assert _db_scalar("SELECT winner_team_id::text FROM matches WHERE id = %s::uuid", (match_id,)) == home

    kept = client.patch(f"/matches/{match_id}", json={"match_date": "2025-03-04"}).json()["match"]
    assert kept["description"] == "edited"
    cleared = client.patch(f"/matches/{match_id}", json={"description": None}).json()["match"]
    assert cleared["description"] is None and cleared["match_date"] == "2025-03-04"

    assert client.patch(f"/matches/{match_id}", json={"description": "x" * 2001}).status_code == 422
    missing = client.patch(f"/matches/{uuid4()}", json={"description": "x"})
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "MATCH_NOT_FOUND")
    assert client.delete(f"/matches/{match_id}").status_code == 405


# --- migration safety, in throwaway schemas so the shared tables are never touched -------------


def _schema_url(base: str, schema: str) -> str:
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}options=-csearch_path%3D{schema}"


@pytest.fixture
def scratch_schema():
    base = _required_env()["DATABASE_URL"]
    schema = f"mig_{uuid4().hex[:10]}"
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
    try:
        yield base, schema
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")


def test_link_migration_is_additive_idempotent_and_keeps_data(scratch_schema) -> None:
    base, schema = scratch_schema
    url = _schema_url(base, schema)
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            for migration_dir in MIGRATION_DIRS:
                for migration_file in sorted(migration_dir.glob("*.sql")):
                    if migration_file != LINK_MIGRATION:
                        cur.execute(migration_file.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO users (id, email_normalized, password_hash, created_at, updated_at) VALUES ('u1', 'u1@x.com', 'h', NOW(), NOW())")
            cur.execute("INSERT INTO teams (id, owner_user_id, name, short_name, city, country, created_at) VALUES (gen_random_uuid(), 'u1', 'A', 'A', 'c', 'c', NOW()) RETURNING id")
            team_id = cur.fetchone()[0]
            cur.execute("INSERT INTO teams (id, owner_user_id, name, short_name, city, country, created_at) VALUES (gen_random_uuid(), 'u1', 'B', 'B', 'c', 'c', NOW()) RETURNING id")
            other_team_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO matches (id, owner_user_id, home_team_id, away_team_id, match_date) "
                "VALUES (gen_random_uuid(), 'u1', %s, %s, '2024-01-01') RETURNING id",
                (team_id, other_team_id),
            )
            match_id = cur.fetchone()[0]
            for index in range(3):
                cur.execute(
                    "INSERT INTO videos (id, team_id, owner_user_id, storage_key, title, status, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), %s, 'u1', %s, 'V', 'READY', NOW(), NOW())",
                    (team_id, f"k{index}"),
                )
        conn.commit()

        def snapshot():
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM videos")
                videos = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM matches")
                matches = cur.fetchone()[0]
                cur.execute("SELECT id, storage_key, title, status, updated_at FROM videos ORDER BY storage_key")
                rows = cur.fetchall()
            conn.commit()
            return videos, matches, rows

        before = snapshot()
        assert before[:2] == (3, 1)
        sql = LINK_MIGRATION.read_text(encoding="utf-8")
        for _ in range(2):  # the second run must be a no-op
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            assert snapshot() == before

        with conn.cursor() as cur:
            # SET LOCAL lock_timeout must not outlive the migration's transaction.
            cur.execute("SHOW lock_timeout")
            assert cur.fetchone()[0] == "0"
            cur.execute("SELECT COUNT(*) FROM videos WHERE match_id IS NOT NULL")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT is_nullable FROM information_schema.columns WHERE table_schema = %s AND table_name = 'videos' AND column_name = 'match_id'", (schema,))
            assert cur.fetchone()[0] == "YES"
            cur.execute("SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND indexname = 'idx_videos_match_id'", (schema,))
            assert "WHERE (match_id IS NOT NULL)" in cur.fetchone()[0]
            # ON DELETE SET NULL: removing a match never removes its videos.
            cur.execute("UPDATE videos SET match_id = %s WHERE storage_key = 'k0'", (match_id,))
            cur.execute("DELETE FROM matches WHERE id = %s", (match_id,))
            cur.execute("SELECT COUNT(*), COUNT(match_id) FROM videos")
            assert cur.fetchone() == (3, 0)
        conn.rollback()


def test_link_migration_file_is_additive_only() -> None:
    sql = LINK_MIGRATION.read_text(encoding="utf-8")
    statements = [line.strip() for line in sql.splitlines() if line.strip()]
    assert statements == [
        "SET LOCAL lock_timeout = '5s';",
        "ALTER TABLE videos ADD COLUMN IF NOT EXISTS match_id UUID NULL REFERENCES matches(id) ON DELETE SET NULL;",
        "CREATE INDEX IF NOT EXISTS idx_videos_match_id ON videos (match_id) WHERE match_id IS NOT NULL;",
    ]
    for word in ("DROP", "TRUNCATE", "DELETE", "RENAME", "UPDATE", "INSERT"):
        assert word not in sql.upper().replace("ON DELETE SET NULL", "")


def test_apply_migrations_script_records_link_migration_once(scratch_schema) -> None:
    base, schema = scratch_schema
    env = {**os.environ, "DATABASE_URL": _schema_url(base, schema), "PYTHONPATH": "."}
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "scripts/apply_migrations.py"], env=env, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
    with psycopg.connect(_schema_url(base, schema)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM schema_migrations WHERE filename = %s", (LINK_MIGRATION.as_posix(),))
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT filename FROM schema_migrations ORDER BY applied_at, filename")
            names = [row[0] for row in cur.fetchall()]
    # matches migrations are applied before the video one that references them.
    assert names.index("src/infrastructure/matches/migrations/001_match_stats_foundation.sql") < names.index(
        LINK_MIGRATION.as_posix()
    )
