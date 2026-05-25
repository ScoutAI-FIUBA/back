from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from src.application.auth.use_cases import HardDeleteUserCommand


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


def _apply_auth_migration(database_url: str) -> None:
    migration_dir = Path("src/infrastructure/auth/migrations")
    migration_files = sorted(migration_dir.glob("*.sql"))

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for migration_file in migration_files:
                sql = migration_file.read_text(encoding="utf-8")
                cur.execute(sql)
        conn.commit()


def _truncate_auth_tables(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE auth_refresh_sessions, users RESTART IDENTITY CASCADE")
        conn.commit()


@pytest.fixture(scope="session", autouse=True)
def _integration_schema_ready() -> None:
    env = _required_env()
    _apply_auth_migration(env["DATABASE_URL"])


@pytest.fixture(autouse=True)
def _auth_tables_clean() -> None:
    env = _required_env()
    _truncate_auth_tables(env["DATABASE_URL"])


@pytest.fixture
def client() -> TestClient:
    from src.interfaces.http.main import create_app

    env = _required_env()
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    app = create_app()
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _register(client: TestClient, email: str, password: str = "supersecret123"):
    return client.post("/auth/register", json={"email": email, "password": password})


def _login(client: TestClient, email: str, password: str = "supersecret123"):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_register_happy_path_and_duplicate_email(client: TestClient) -> None:
    email = f"register-{uuid4().hex}@example.com"
    first = _register(client, email)

    assert first.status_code == 200
    body = first.json()
    assert body["user"]["email"] == email
    assert body["user"]["role"] == "user"
    assert "password_hash" not in body["user"]

    duplicate = _register(client, email)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "AUTH_EMAIL_ALREADY_EXISTS"


def test_login_happy_path_sets_refresh_cookie_and_invalid_credentials(client: TestClient) -> None:
    email = f"login-{uuid4().hex}@example.com"
    _register(client, email)

    login = _login(client, email)
    assert login.status_code == 200
    payload = login.json()
    assert payload["token_type"] == "Bearer"
    assert payload["expires_in"] == 900
    assert "refresh_token" not in payload

    cookie = login.headers.get("set-cookie", "").lower()
    assert "refresh_token=" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
    assert "path=/auth" in cookie

    wrong_password = _login(client, email, "bad-password")
    assert wrong_password.status_code == 401
    assert wrong_password.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"


def test_refresh_happy_path_invalid_missing_and_reuse_paths(client: TestClient) -> None:
    email = f"refresh-{uuid4().hex}@example.com"
    _register(client, email)
    login = _login(client, email)
    refresh_token = login.cookies.get("refresh_token")
    assert refresh_token

    refreshed = client.post("/auth/refresh", cookies={"refresh_token": refresh_token})
    assert refreshed.status_code == 200
    refreshed_token = refreshed.cookies.get("refresh_token")
    assert refreshed_token and refreshed_token != refresh_token
    assert refreshed.json()["token_type"] == "Bearer"

    cookie_header = refreshed.headers.get("set-cookie", "").lower()
    assert "httponly" in cookie_header
    assert "secure" in cookie_header
    assert "samesite=strict" in cookie_header

    from src.interfaces.http.main import create_app

    with TestClient(create_app(), base_url="https://testserver") as missing_cookie_client:
        no_cookie = missing_cookie_client.post("/auth/refresh")
    assert no_cookie.status_code == 401
    assert no_cookie.json()["error"]["code"] == "AUTH_UNAUTHORIZED"

    invalid_cookie = client.post("/auth/refresh", cookies={"refresh_token": "not-a-real-token"})
    assert invalid_cookie.status_code == 401
    assert invalid_cookie.json()["error"]["code"] == "AUTH_TOKEN_INVALID"

    reused_old = client.post("/auth/refresh", cookies={"refresh_token": refresh_token})
    assert reused_old.status_code == 401
    assert reused_old.json()["error"]["code"] == "AUTH_REFRESH_REUSED"

    family_revoked = client.post("/auth/refresh", cookies={"refresh_token": refreshed_token})
    assert family_revoked.status_code == 401
    assert family_revoked.json()["error"]["code"] == "AUTH_REFRESH_REUSED"


def test_refresh_expired_session_returns_reuse_contract(client: TestClient) -> None:
    env = _required_env()
    email = f"refresh-expired-{uuid4().hex}@example.com"
    _register(client, email)
    login = _login(client, email)
    refresh_token = login.cookies.get("refresh_token")
    assert refresh_token

    with psycopg.connect(env["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE auth_refresh_sessions SET expires_at = NOW() - INTERVAL '1 second'")
        conn.commit()

    expired = client.post("/auth/refresh", cookies={"refresh_token": refresh_token})
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "AUTH_REFRESH_REUSED"
    assert expired.json()["error"]["message"] == "Refresh token reuse detected"


def test_logout_happy_path_clears_cookie_and_revokes_session(client: TestClient) -> None:
    email = f"logout-{uuid4().hex}@example.com"
    _register(client, email)
    login = _login(client, email)
    access_token = login.json()["access_token"]
    refresh_token = login.cookies.get("refresh_token")
    assert refresh_token

    logout = client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        cookies={"refresh_token": refresh_token},
    )
    assert logout.status_code == 204
    cookie = logout.headers.get("set-cookie", "").lower()
    assert "refresh_token=\"\"" in cookie
    assert "max-age=0" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
    assert "path=/auth" in cookie

    reused_after_logout = client.post("/auth/refresh", cookies={"refresh_token": refresh_token})
    assert reused_after_logout.status_code == 401
    assert reused_after_logout.json()["error"]["code"] == "AUTH_REFRESH_REUSED"


def test_me_happy_path_and_invalid_token_paths(client: TestClient) -> None:
    email = f"me-{uuid4().hex}@example.com"
    _register(client, email)
    login = _login(client, email)
    access_token = login.json()["access_token"]

    ok = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert ok.status_code == 200
    assert ok.json()["user"]["email"] == email

    missing = client.get("/auth/me")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "AUTH_UNAUTHORIZED"

    bad_scheme = client.get("/auth/me", headers={"Authorization": "Basic abc"})
    assert bad_scheme.status_code == 401
    assert bad_scheme.json()["error"]["code"] == "AUTH_TOKEN_INVALID"

    invalid = client.get("/auth/me", headers={"Authorization": "Bearer invalid-token"})
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "AUTH_TOKEN_INVALID"


def test_delete_me_soft_delete_is_exposed_and_revokes_access(client: TestClient) -> None:
    email = f"delete-{uuid4().hex}@example.com"
    _register(client, email)
    login = _login(client, email)
    access_token = login.json()["access_token"]
    refresh_token = login.cookies.get("refresh_token")
    assert refresh_token

    deleted = client.delete("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert deleted.status_code == 204

    me_after_delete = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_after_delete.status_code == 401
    assert me_after_delete.json()["error"]["code"] == "AUTH_UNAUTHORIZED"

    refresh_after_delete = client.post("/auth/refresh", cookies={"refresh_token": refresh_token})
    assert refresh_after_delete.status_code == 401
    assert refresh_after_delete.json()["error"]["code"] == "AUTH_REFRESH_REUSED"

    login_after_delete = _login(client, email)
    assert login_after_delete.status_code == 401
    assert login_after_delete.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"


def test_hard_delete_user_succeeds_when_refresh_sessions_exist(client: TestClient) -> None:
    env = _required_env()
    email = f"hard-delete-{uuid4().hex}@example.com"
    _register(client, email)
    login = _login(client, email)
    refresh_token = login.cookies.get("refresh_token")
    assert refresh_token

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.status_code == 200
    user_id = me.json()["user"]["id"]

    hard_delete = client.app.state.auth_hard_delete_user_use_case
    hard_delete.execute(HardDeleteUserCommand(user_id=user_id))

    with psycopg.connect(env["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE id = %s", (user_id,))
            users_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM auth_refresh_sessions WHERE user_id = %s", (user_id,))
            sessions_count = cur.fetchone()[0]

    assert users_count == 0
    assert sessions_count == 0
