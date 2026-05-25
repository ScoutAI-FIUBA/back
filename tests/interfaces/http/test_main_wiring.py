from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient

from src.interfaces.http.main import create_app


class _FakeConnection:
    closed = False

    def cursor(self, *args, **kwargs):
        raise RuntimeError("cursor should not be called during app bootstrap")

    def transaction(self):
        class _Tx:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc, tb):
                return False

        return _Tx()


class TestMainWiring(unittest.TestCase):
    def test_create_app_registers_health_auth_players_and_teams_routes(self) -> None:
        env = {
            "AUTH_JWT_SECRET": "secret",
            "AUTH_REFRESH_SECRET": "refresh",
            "AUTH_JWT_ISSUER": "scoutai",
            "AUTH_JWT_AUDIENCE": "scoutai-client",
            "DATABASE_URL": "postgresql://test",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("src.interfaces.http.main.psycopg.connect", return_value=_FakeConnection()):
                app = create_app()

        paths = {route.path for route in app.routes}
        self.assertIn("/health", paths)
        self.assertIn("/db-health", paths)
        for path in (
            "/auth/register",
            "/auth/login",
            "/auth/refresh",
            "/auth/logout",
            "/auth/me",
            "/players",
            "/players/{player_id}",
            "/players/{player_id}/team/{team_id}",
            "/teams",
            "/teams/{team_id}",
        ):
            self.assertIn(path, paths)

    def test_db_health_returns_ok_when_database_is_reachable(self) -> None:
        env = {
            "AUTH_JWT_SECRET": "secret",
            "AUTH_REFRESH_SECRET": "refresh",
            "AUTH_JWT_ISSUER": "scoutai",
            "AUTH_JWT_AUDIENCE": "scoutai-client",
            "DATABASE_URL": "postgresql://test",
        }

        class _HealthyConnection:
            closed = False

            def cursor(self, *args, **kwargs):
                class _Cursor:
                    def execute(self, *_a, **_k):
                        return None

                    def fetchone(self):
                        return (1,)

                    def __enter__(self):
                        return self

                    def __exit__(self, *_):
                        return False

                return _Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        with patch.dict(os.environ, env, clear=False):
            with patch(
                "src.interfaces.http.main.psycopg.connect",
                return_value=_HealthyConnection(),
            ):
                app = create_app()
                with TestClient(app) as client:
                    response = client.get("/db-health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_db_health_returns_503_without_leaking_internal_errors(self) -> None:
        env = {
            "AUTH_JWT_SECRET": "secret",
            "AUTH_REFRESH_SECRET": "refresh",
            "AUTH_JWT_ISSUER": "scoutai",
            "AUTH_JWT_AUDIENCE": "scoutai-client",
            "DATABASE_URL": "postgresql://test",
        }

        with patch.dict(os.environ, env, clear=False):
            with patch(
                "src.interfaces.http.main.psycopg.connect",
                side_effect=psycopg.OperationalError("secret-host.internal:5432 refused"),
            ):
                app = create_app()
                with TestClient(app) as client:
                    response = client.get("/db-health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Database unavailable")
        self.assertNotIn("secret-host", response.text)

    def test_create_app_requires_cors_origins_in_production(self) -> None:
        env = {
            "APP_ENV": "production",
            "AUTH_JWT_SECRET": "secret",
            "AUTH_REFRESH_SECRET": "refresh",
            "AUTH_JWT_ISSUER": "scoutai",
            "AUTH_JWT_AUDIENCE": "scoutai-client",
            "DATABASE_URL": "postgresql://test",
        }

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "CORS_ORIGINS"):
                create_app()

    def test_create_app_falls_back_when_db_health_timeout_is_invalid(self) -> None:
        env = {
            "DB_HEALTH_CONNECT_TIMEOUT_SECONDS": "not-a-number",
            "AUTH_JWT_SECRET": "secret",
            "AUTH_REFRESH_SECRET": "refresh",
            "AUTH_JWT_ISSUER": "scoutai",
            "AUTH_JWT_AUDIENCE": "scoutai-client",
            "DATABASE_URL": "postgresql://test",
        }

        with patch.dict(os.environ, env, clear=False):
            with patch("src.interfaces.http.main.psycopg.connect", return_value=_FakeConnection()):
                app = create_app()

        self.assertIsNotNone(app)

    def test_create_app_rejects_mixed_wildcard_cors_origins(self) -> None:
        env = {
            "APP_ENV": "production",
            "CORS_ORIGINS": "*,https://example.com",
            "AUTH_JWT_SECRET": "secret",
            "AUTH_REFRESH_SECRET": "refresh",
            "AUTH_JWT_ISSUER": "scoutai",
            "AUTH_JWT_AUDIENCE": "scoutai-client",
            "DATABASE_URL": "postgresql://test",
        }

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "cannot mix"):
                create_app()

    def test_create_app_fails_fast_when_required_env_is_missing(self) -> None:
        env = {
            "AUTH_REFRESH_SECRET": "refresh",
            "AUTH_JWT_ISSUER": "scoutai",
            "AUTH_JWT_AUDIENCE": "scoutai-client",
            "DATABASE_URL": "postgresql://test",
        }

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Missing required environment variable: AUTH_JWT_SECRET"):
                create_app()

    def test_auth_validation_errors_use_auth_error_envelope(self) -> None:
        env = {
            "AUTH_JWT_SECRET": "secret",
            "AUTH_REFRESH_SECRET": "refresh",
            "AUTH_JWT_ISSUER": "scoutai",
            "AUTH_JWT_AUDIENCE": "scoutai-client",
            "DATABASE_URL": "postgresql://test",
        }
        with patch.dict(os.environ, env, clear=False):
            app = create_app()

        with TestClient(app) as client:
            invalid = client.post("/auth/register", json={"email": "x", "password": "short"})

        self.assertEqual(invalid.status_code, 400)
        body = invalid.json()
        self.assertEqual(body["error"]["code"], "AUTH_VALIDATION_ERROR")
        self.assertIn("errors", body["error"]["details"])

    def test_global_auth_protects_non_public_routes_by_default(self) -> None:
        env = {
            "AUTH_JWT_SECRET": "secret",
            "AUTH_REFRESH_SECRET": "refresh",
            "AUTH_JWT_ISSUER": "scoutai",
            "AUTH_JWT_AUDIENCE": "scoutai-client",
            "DATABASE_URL": "postgresql://test",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("src.interfaces.http.main.psycopg.connect", return_value=_FakeConnection()):
                app = create_app()

        with TestClient(app) as client:
            protected = client.get("/players")
            public = client.post("/auth/login", json={"email": "x", "password": ""})

        self.assertEqual(protected.status_code, 401)
        self.assertEqual(protected.json()["error"]["code"], "AUTH_UNAUTHORIZED")
        self.assertEqual(public.status_code, 400)
        self.assertEqual(public.json()["error"]["code"], "AUTH_VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
