from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

import psycopg

from src.application.auth.ports import AuthIdGeneratorPort, ClockPort, UnitOfWorkPort
from src.application.auth.use_cases import (
    DeleteCurrentUserUseCase,
    GetCurrentUserUseCase,
    HardDeleteUserUseCase,
    LoginUseCase,
    LogoutUseCase,
    RefreshSessionUseCase,
    RegisterUserUseCase,
)
from src.application.players.use_cases import (
    AssignPlayerTeamUseCase,
    CreatePlayerUseCase,
    DeletePlayerUseCase,
    ListPlayersByTeamUseCase,
    ListPlayersUseCase,
    UpdatePlayerUseCase,
)
from src.application.team.use_cases import (
    CreateTeamUseCase,
    DeleteTeamUseCase,
    ListTeamsUseCase,
    UpdateTeamUseCase,
)
from src.infrastructure.auth.argon2_password_hasher import Argon2PasswordHasher
from src.infrastructure.auth.jwt_access_token_resolver import JWTAccessTokenResolver
from src.infrastructure.auth.jwt_token_issuer import JWTTokenIssuer
from src.infrastructure.auth.opaque_refresh_token_service import OpaqueRefreshTokenService
from src.infrastructure.auth.postgres_repositories import (
    PostgresRefreshSessionRepository,
    PostgresUserRepository,
)
from src.infrastructure.players.postgres_player_repository import PostgresPlayerRepository
from src.infrastructure.team.postgres_repository import PostgresTeamRepository


class OperationConnection:
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


class SystemClock(ClockPort):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class UUIDIds(AuthIdGeneratorPort):
    def new_id(self) -> str:
        return str(uuid.uuid4())

    def new_jti(self) -> str:
        return str(uuid.uuid4())

    def new_family_id(self) -> str:
        return str(uuid.uuid4())


class PsycopgUnitOfWork(UnitOfWorkPort):
    def __init__(self, connection: OperationConnection) -> None:
        self._connection = connection

    @contextmanager
    def transaction(self):
        with self._connection.transaction():
            yield


@dataclass(frozen=True)
class HttpDependencies:
    register_user_use_case: RegisterUserUseCase
    login_use_case: LoginUseCase
    refresh_session_use_case: RefreshSessionUseCase
    logout_use_case: LogoutUseCase
    get_current_user_use_case: GetCurrentUserUseCase
    delete_current_user_use_case: DeleteCurrentUserUseCase
    hard_delete_user_use_case: HardDeleteUserUseCase
    create_team_use_case: CreateTeamUseCase
    list_teams_use_case: ListTeamsUseCase
    update_team_use_case: UpdateTeamUseCase
    delete_team_use_case: DeleteTeamUseCase
    create_player_use_case: CreatePlayerUseCase
    list_players_use_case: ListPlayersUseCase
    list_players_by_team_use_case: ListPlayersByTeamUseCase
    update_player_use_case: UpdatePlayerUseCase
    delete_player_use_case: DeletePlayerUseCase
    assign_player_team_use_case: AssignPlayerTeamUseCase
    access_token_resolver: JWTAccessTokenResolver


def build_http_dependencies(
    *,
    jwt_secret: str,
    refresh_secret: str,
    jwt_issuer: str,
    jwt_audience: str,
    database_url: str,
) -> HttpDependencies:
    conn = OperationConnection(database_url)
    users_repo = PostgresUserRepository(connection=conn)
    refresh_repo = PostgresRefreshSessionRepository(connection=conn)
    players_repo = PostgresPlayerRepository(connection=conn)
    teams_repo = PostgresTeamRepository(connection=conn)
    password_hasher = Argon2PasswordHasher()
    token_issuer = JWTTokenIssuer(secret=jwt_secret, issuer=jwt_issuer, audience=jwt_audience)
    refresh_tokens = OpaqueRefreshTokenService(secret=refresh_secret)
    access_token_resolver = JWTAccessTokenResolver(
        secret=jwt_secret,
        issuer=jwt_issuer,
        audience=jwt_audience,
    )
    clock = SystemClock()
    ids = UUIDIds()
    uow = PsycopgUnitOfWork(conn)

    return HttpDependencies(
        register_user_use_case=RegisterUserUseCase(
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
        refresh_session_use_case=RefreshSessionUseCase(
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
        get_current_user_use_case=GetCurrentUserUseCase(users=users_repo),
        delete_current_user_use_case=DeleteCurrentUserUseCase(
            users=users_repo,
            refresh_sessions=refresh_repo,
            clock=clock,
            uow=uow,
        ),
        hard_delete_user_use_case=HardDeleteUserUseCase(
            users=users_repo,
            refresh_sessions=refresh_repo,
            clock=clock,
            uow=uow,
        ),
        create_team_use_case=CreateTeamUseCase(teams=teams_repo, clock=clock, ids=ids),
        list_teams_use_case=ListTeamsUseCase(teams=teams_repo),
        update_team_use_case=UpdateTeamUseCase(teams=teams_repo),
        delete_team_use_case=DeleteTeamUseCase(teams=teams_repo),
        create_player_use_case=CreatePlayerUseCase(players=players_repo, ids=ids, uow=uow),
        list_players_use_case=ListPlayersUseCase(players=players_repo),
        list_players_by_team_use_case=ListPlayersByTeamUseCase(players=players_repo),
        update_player_use_case=UpdatePlayerUseCase(players=players_repo, uow=uow),
        delete_player_use_case=DeletePlayerUseCase(players=players_repo, uow=uow),
        assign_player_team_use_case=AssignPlayerTeamUseCase(
            players=players_repo,
            teams=teams_repo,
            uow=uow,
        ),
        access_token_resolver=access_token_resolver,
    )
