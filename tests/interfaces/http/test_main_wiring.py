from __future__ import annotations

import os
import unittest
from unittest.mock import patch

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
    def test_create_app_registers_health_and_auth_routes(self) -> None:
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
        for path in ("/auth/register", "/auth/login", "/auth/refresh", "/auth/logout", "/auth/me"):
            self.assertIn(path, paths)

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


if __name__ == "__main__":
    unittest.main()
