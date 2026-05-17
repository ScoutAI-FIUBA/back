from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
import uuid

from fastapi import FastAPI
import psycopg

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


class _LazyConnection:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._connection: psycopg.Connection | None = None

    def _get(self) -> psycopg.Connection:
        if self._connection is None or self._connection.closed:
            self._connection = psycopg.connect(self._dsn)
        return self._connection

    def cursor(self, *args, **kwargs):
        return self._get().cursor(*args, **kwargs)

    def transaction(self):
        return self._get().transaction()


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
    def __init__(self, connection: _LazyConnection) -> None:
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

    conn = _LazyConnection(database_url)
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

    @app.get("/health")
    def health() -> dict[str, str]:
        use_case = GetHealthStatus(InMemoryHealthAdapter())
        status = use_case.execute()
        return {"status": status.status}

    return app


app = create_app()
