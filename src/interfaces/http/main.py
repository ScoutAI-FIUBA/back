from __future__ import annotations

from fastapi import FastAPI
import psycopg

from src.interfaces.http.bootstrap.config import (
    configure_cors,
    db_health_connect_timeout_seconds,
    require_env,
)
from src.interfaces.http.bootstrap.dependencies import build_http_dependencies
from src.interfaces.http.bootstrap.health_routes import register_health_routes
from src.interfaces.http.bootstrap.router_wiring import wire_routers
from src.interfaces.http.errors.error_handlers import register_error_handlers
from src.interfaces.http.middleware.auth_middleware import create_require_authenticated_user_middleware


def create_app() -> FastAPI:
    """Builds the HTTP application and wires boundary contracts.

    Startup fails fast when required auth/database configuration is missing, then
    wires dependencies, routers, authentication middleware, error handlers, and
    health endpoints in a single composition root.
    """

    app = FastAPI(title="ScoutAI Backend", version="0.1.0")

    jwt_secret = require_env("AUTH_JWT_SECRET")
    refresh_secret = require_env("AUTH_REFRESH_SECRET")
    jwt_issuer = require_env("AUTH_JWT_ISSUER")
    jwt_audience = require_env("AUTH_JWT_AUDIENCE")
    database_url = require_env("DATABASE_URL")
    db_health_connect_timeout = db_health_connect_timeout_seconds()

    deps = build_http_dependencies(
        jwt_secret=jwt_secret,
        refresh_secret=refresh_secret,
        jwt_issuer=jwt_issuer,
        jwt_audience=jwt_audience,
        database_url=database_url,
    )
    wire_routers(app, deps)

    app.state.auth_hard_delete_user_use_case = deps.hard_delete_user_use_case
    require_authenticated_user_handler = create_require_authenticated_user_middleware(
        resolve_subject=deps.access_token_resolver.resolve_subject,
    )

    @app.middleware("http")
    async def require_authenticated_user(request, call_next):
        return await require_authenticated_user_handler(request, call_next)

    # Registered AFTER the auth middleware on purpose: Starlette wraps each new middleware
    # around the previous ones, so CORS must be added last to be outermost. Otherwise a 401
    # from the auth middleware leaves without CORS headers, the browser hides it, and the
    # frontend can never see that the token expired and refresh the session.
    configure_cors(app)

    register_error_handlers(app)
    register_health_routes(
        app,
        database_url=database_url,
        db_health_connect_timeout=db_health_connect_timeout,
        connect=psycopg.connect,
    )

    return app
