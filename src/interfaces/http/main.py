from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import psycopg

from src.application.auth.errors import AUTH_VALIDATION_ERROR, AuthError, auth_error_http_status
from src.application.auth.ports import ClockPort, IdGeneratorPort, UnitOfWorkPort
from src.application.auth.use_cases import (
    DeleteCurrentUserUseCase,
    GetCurrentUserUseCase,
    HardDeleteUserUseCase,
    LoginUseCase,
    LogoutUseCase,
    RefreshSessionUseCase,
    RegisterUserUseCase,
)
from src.application.use_cases import GetHealthStatus
from src.infrastructure.auth.argon2_password_hasher import Argon2PasswordHasher
from src.infrastructure.auth.jwt_access_token_resolver import JWTAccessTokenResolver
from src.infrastructure.auth.jwt_token_issuer import JWTTokenIssuer
from src.infrastructure.auth.opaque_refresh_token_service import OpaqueRefreshTokenService
from src.infrastructure.auth.postgres_repositories import (
    PostgresRefreshSessionRepository,
    PostgresUserRepository,
)
from src.infrastructure.health_adapter import InMemoryHealthAdapter
from src.interfaces.http.auth_router import create_auth_router


class _OperationConnection:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._current_connection: ContextVar[psycopg.Connection | None] = ContextVar(
            "auth_db_connection",
            default=None,
        )

    @contextmanager
    def cursor(self, *args, **kwargs):
        current = self._current_connection.get()
        if current is not None and not current.closed:
            with current.cursor(*args, **kwargs) as cursor:
                yield cursor
            return

        with psycopg.connect(self._dsn) as connection:
            with connection.cursor(*args, **kwargs) as cursor:
                yield cursor

    @contextmanager
    def transaction(self):
        current = self._current_connection.get()
        if current is not None and not current.closed:
            with current.transaction():
                yield
            return

        with psycopg.connect(self._dsn) as connection:
            token = self._current_connection.set(connection)
            try:
                with connection.transaction():
                    yield
            finally:
                self._current_connection.reset(token)


class _SystemClock(ClockPort):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class _UUIDIds(IdGeneratorPort):
    def new_id(self) -> str:
        return str(uuid.uuid4())

    def new_jti(self) -> str:
        return str(uuid.uuid4())

    def new_family_id(self) -> str:
        return str(uuid.uuid4())


class _PsycopgUnitOfWork(UnitOfWorkPort):
    def __init__(self, connection: _OperationConnection) -> None:
        self._connection = connection

    @contextmanager
    def transaction(self):
        with self._connection.transaction():
            yield


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def create_app() -> FastAPI:
    app = FastAPI(title="ScoutAI Backend", version="0.1.0")

    jwt_secret = _require_env("AUTH_JWT_SECRET")
    refresh_secret = _require_env("AUTH_REFRESH_SECRET")
    jwt_issuer = _require_env("AUTH_JWT_ISSUER")
    jwt_audience = _require_env("AUTH_JWT_AUDIENCE")
    database_url = _require_env("DATABASE_URL")

    conn = _OperationConnection(database_url)
    users_repo = PostgresUserRepository(connection=conn)
    refresh_repo = PostgresRefreshSessionRepository(connection=conn)
    password_hasher = Argon2PasswordHasher()
    token_issuer = JWTTokenIssuer(secret=jwt_secret, issuer=jwt_issuer, audience=jwt_audience)
    refresh_tokens = OpaqueRefreshTokenService(secret=refresh_secret)
    access_token_resolver = JWTAccessTokenResolver(
        secret=jwt_secret,
        issuer=jwt_issuer,
        audience=jwt_audience,
    )
    clock = _SystemClock()
    ids = _UUIDIds()
    uow = _PsycopgUnitOfWork(conn)

    app.include_router(
        create_auth_router(
            register_use_case=RegisterUserUseCase(
                users=users_repo,
                password_hasher=password_hasher,
                clock=clock,
                ids=ids,
                uow=uow,
            ),
            login_use_case=LoginUseCase(
                users=users_repo,
                refresh_sessions=refresh_repo,
                password_hasher=password_hasher,
                token_issuer=token_issuer,
                refresh_tokens=refresh_tokens,
                clock=clock,
                ids=ids,
                uow=uow,
            ),
            refresh_use_case=RefreshSessionUseCase(
                users=users_repo,
                refresh_sessions=refresh_repo,
                token_issuer=token_issuer,
                refresh_tokens=refresh_tokens,
                clock=clock,
                ids=ids,
                uow=uow,
            ),
            logout_use_case=LogoutUseCase(
                refresh_sessions=refresh_repo,
                refresh_tokens=refresh_tokens,
                clock=clock,
                uow=uow,
            ),
            current_user_use_case=GetCurrentUserUseCase(users=users_repo),
            delete_current_user_use_case=DeleteCurrentUserUseCase(
                users=users_repo,
                refresh_sessions=refresh_repo,
                clock=clock,
                uow=uow,
            ),
            access_token_resolver=access_token_resolver.resolve_subject,
        )
    )

    app.state.auth_hard_delete_user_use_case = HardDeleteUserUseCase(
        users=users_repo,
        refresh_sessions=refresh_repo,
        clock=clock,
        uow=uow,
    )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/auth"):
            auth_error = AuthError(
                code=AUTH_VALIDATION_ERROR,
                message="Invalid auth payload",
                details={"errors": exc.errors()},
            )
            return JSONResponse(
                status_code=auth_error_http_status(auth_error.code),
                content=auth_error.to_envelope(),
            )
        return await request_validation_exception_handler(request, exc)

    @app.get("/health")
    def health() -> dict[str, str]:
        use_case = GetHealthStatus(InMemoryHealthAdapter())
        status = use_case.execute()
        return {"status": status.status}

    return app


app = create_app()
