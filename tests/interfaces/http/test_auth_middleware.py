from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.auth.errors import AuthError
from src.interfaces.http.middleware.auth_middleware import (
    PUBLIC_ROUTES,
    create_require_authenticated_user_middleware,
)


class TestAuthMiddleware(unittest.TestCase):
    def test_public_route_bypasses_auth(self) -> None:
        app = FastAPI()

        @app.post("/auth/login")
        def login() -> dict[str, str]:
            return {"status": "ok"}

        middleware = create_require_authenticated_user_middleware(
            resolve_subject=lambda token: "user-1",
            public_routes=PUBLIC_ROUTES,
        )

        @app.middleware("http")
        async def require_authenticated_user(request, call_next):
            return await middleware(request, call_next)

        with TestClient(app) as client:
            response = client.post("/auth/login")

        self.assertEqual(response.status_code, 200)

    def test_missing_authorization_header_returns_401(self) -> None:
        app = FastAPI()

        @app.get("/players")
        def players() -> dict[str, str]:
            return {"status": "ok"}

        middleware = create_require_authenticated_user_middleware(
            resolve_subject=lambda token: "user-1",
            public_routes=PUBLIC_ROUTES,
        )

        @app.middleware("http")
        async def require_authenticated_user(request, call_next):
            return await middleware(request, call_next)

        with TestClient(app) as client:
            response = client.get("/players")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "AUTH_UNAUTHORIZED")

    def test_invalid_token_uses_auth_error_envelope(self) -> None:
        app = FastAPI()

        @app.get("/players")
        def players() -> dict[str, str]:
            return {"status": "ok"}

        def _raise_auth_error(_: str) -> str:
            raise AuthError(code="AUTH_TOKEN_INVALID", message="Invalid token")

        middleware = create_require_authenticated_user_middleware(
            resolve_subject=_raise_auth_error,
            public_routes=PUBLIC_ROUTES,
        )

        @app.middleware("http")
        async def require_authenticated_user(request, call_next):
            return await middleware(request, call_next)

        with TestClient(app) as client:
            response = client.get("/players", headers={"authorization": "Bearer invalid"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "AUTH_TOKEN_INVALID")


if __name__ == "__main__":
    unittest.main()
