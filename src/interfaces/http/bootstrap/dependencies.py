from __future__ import annotations

"""HTTP dependency bootstrap wiring.

Composes infrastructure adapters and application use cases into a single object
consumed by route registration.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import os
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
from src.application.clip_collections.use_cases import (
    AddClipBatchUseCase,
    AddClipUseCase,
    CreateClipCollectionUseCase,
    DeleteClipCollectionItemUseCase,
    ExportClipItemUseCase,
    GetClipCollectionDetailUseCase,
    ListClipCollectionsUseCase,
)
from src.application.matches.use_cases import (
    CreateMatchUseCase,
    GetMatchStatsUseCase,
    GetMatchUseCase,
    GetPlayerMatchesUseCase,
    GetTeamStatsUseCase,
    ListMatchesUseCase,
    ReplaceMatchStatsUseCase,
)
from src.application.players.use_cases import (
    AssignPlayerTeamUseCase,
    CreatePlayerUseCase,
    DeletePlayerUseCase,
    GetPlayerStatsUseCase,
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
from src.application.jobs.ports import ProcessingServicePort
from src.application.jobs.use_cases import (
    GetJobResultsUseCase,
    GetProcessingJobUseCase,
    ListVideoJobsUseCase,
    RecordJobProgressUseCase,
    SubmitProcessingJobUseCase,
)
from src.application.stats.use_cases import GetCourtPositionsUseCase, GetGameStatsUseCase
from src.application.video.errors import TEAM_NOT_FOUND, VideoError
from src.application.video.ports import TeamAccessPort
from src.application.video.use_cases import (
    AbortVideoUploadUseCase,
    CompleteVideoUploadUseCase,
    DeleteVideoUseCase,
    GetVideoUseCase,
    InitVideoUploadUseCase,
    ListVideosUseCase,
    UpdateVideoUseCase,
)
from src.infrastructure.auth.argon2_password_hasher import Argon2PasswordHasher
from src.infrastructure.auth.jwt_access_token_resolver import JWTAccessTokenResolver
from src.infrastructure.auth.jwt_token_issuer import JWTTokenIssuer
from src.infrastructure.auth.opaque_refresh_token_service import OpaqueRefreshTokenService
from src.infrastructure.auth.postgres_repositories import (
    PostgresRefreshSessionRepository,
    PostgresUserRepository,
)
from src.infrastructure.clip_collections.ffmpeg_clip_exporter import FFmpegClipExporter
from src.infrastructure.clip_collections.postgres_repository import PostgresClipCollectionRepository
from src.infrastructure.jobs.http_processing_service import (
    HttpProcessingService,
    UnconfiguredProcessingService,
)
from src.infrastructure.stats.r2_artifact_reader import R2ArtifactReader, UnavailableArtifactReader
from src.infrastructure.jobs.r2_artifact_urls import R2ArtifactUrls, UnavailableArtifactUrls
from src.infrastructure.jobs.postgres_job_repository import (
    PostgresJobRepository,
    PostgresVideoLookup,
)
from src.infrastructure.matches.postgres_repository import PostgresMatchRepository
from src.infrastructure.players.postgres_player_repository import PostgresPlayerRepository
from src.infrastructure.team.postgres_repository import PostgresTeamRepository
from src.infrastructure.storage import R2Storage
from src.infrastructure.video.postgres_video_repository import PostgresVideoRepository


class TeamOwnershipAccessAdapter(TeamAccessPort):
    def __init__(self, *, teams: PostgresTeamRepository) -> None:
        self._teams = teams

    def assert_access(self, *, user_id: str, team_id: str) -> None:
        if not self._teams.is_owned_by(team_id=team_id, owner_user_id=user_id):
            raise VideoError(code=TEAM_NOT_FOUND, message="Team not found")


class OperationConnection:
    """Connection wrapper that reuses one psycopg connection per operation.

    Nested repository calls inside the same unit of work share the same
    connection through a context variable. Outside a transaction, each cursor
    call opens its own short-lived connection.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._current_connection: ContextVar[psycopg.Connection | None] = ContextVar(
            "auth_db_connection",
            default=None,
        )

    @contextmanager
    def cursor(self, *args, **kwargs):
        """Yields a cursor bound to current transactional connection when present."""

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
        """Starts/reuses transactional scope and propagates it via context var.

        Invariant: repositories participating in the same use-case transaction
        observe one shared psycopg connection.
        """

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
    """Clock adapter returning UTC timestamps."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class UUIDIds(AuthIdGeneratorPort):
    """ID generator adapter based on UUID4 values."""

    def new_id(self) -> str:
        return str(uuid.uuid4())

    def new_jti(self) -> str:
        return str(uuid.uuid4())

    def new_family_id(self) -> str:
        return str(uuid.uuid4())


class PsycopgUnitOfWork(UnitOfWorkPort):
    """Unit-of-work adapter that centralizes transaction boundaries for use cases."""

    def __init__(self, connection: OperationConnection) -> None:
        self._connection = connection

    @contextmanager
    def transaction(self):
        """Delegates transaction ownership to the operation-scoped connection."""

        with self._connection.transaction():
            yield


@dataclass(frozen=True)
class HttpDependencies:
    """Composed dependency graph consumed by HTTP route factories."""

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
    get_player_stats_use_case: GetPlayerStatsUseCase
    get_player_matches_use_case: GetPlayerMatchesUseCase
    list_players_use_case: ListPlayersUseCase
    list_players_by_team_use_case: ListPlayersByTeamUseCase
    update_player_use_case: UpdatePlayerUseCase
    delete_player_use_case: DeletePlayerUseCase
    assign_player_team_use_case: AssignPlayerTeamUseCase
    create_match_use_case: CreateMatchUseCase
    list_matches_use_case: ListMatchesUseCase
    get_match_use_case: GetMatchUseCase
    replace_match_stats_use_case: ReplaceMatchStatsUseCase
    get_match_stats_use_case: GetMatchStatsUseCase
    get_team_stats_use_case: GetTeamStatsUseCase
    init_video_upload_use_case: InitVideoUploadUseCase
    complete_video_upload_use_case: CompleteVideoUploadUseCase
    abort_video_upload_use_case: AbortVideoUploadUseCase
    list_videos_use_case: ListVideosUseCase
    get_video_use_case: GetVideoUseCase
    update_video_use_case: UpdateVideoUseCase
    delete_video_use_case: DeleteVideoUseCase
    create_clip_collection_use_case: CreateClipCollectionUseCase
    list_clip_collections_use_case: ListClipCollectionsUseCase
    get_clip_collection_detail_use_case: GetClipCollectionDetailUseCase
    add_clip_use_case: AddClipUseCase
    add_clip_batch_use_case: AddClipBatchUseCase
    delete_clip_collection_item_use_case: DeleteClipCollectionItemUseCase
    submit_processing_job_use_case: SubmitProcessingJobUseCase
    get_processing_job_use_case: GetProcessingJobUseCase
    list_video_jobs_use_case: ListVideoJobsUseCase
    record_job_progress_use_case: RecordJobProgressUseCase
    get_job_results_use_case: GetJobResultsUseCase
    game_stats_use_case: GetGameStatsUseCase
    court_positions_use_case: GetCourtPositionsUseCase
    processing_callback_token: str
    export_clip_item_use_case: ExportClipItemUseCase
    access_token_resolver: JWTAccessTokenResolver


def build_processing_service() -> ProcessingServicePort:
    """Pick a processing-service adapter based on configuration.

    Absent configuration is a supported state, not an error: the GPU service is
    developed separately, and every other endpoint must keep working before it
    exists. Submitting a job then fails with a clear 502 rather than preventing
    the app from booting.
    """

    url = (os.getenv("PROCESSING_SERVICE_URL") or "").strip()
    token = (os.getenv("PROCESSING_SERVICE_TOKEN") or "").strip()
    if not url or not token:
        return UnconfiguredProcessingService()
    return HttpProcessingService(endpoint_url=url, auth_token=token)


def build_http_dependencies(
    *,
    jwt_secret: str,
    refresh_secret: str,
    jwt_issuer: str,
    jwt_audience: str,
    database_url: str,
) -> HttpDependencies:
    """Builds concrete adapters/use-cases for the HTTP boundary.

    All auth and player/team repositories share the same operation-scoped
    connection manager so multi-repository use cases can stay transactional.

    Boundary ownership:
    - This function wires concrete adapters only.
    - HTTP route modules receive use-case interfaces, not persistence concerns.
    """

    conn = OperationConnection(database_url)
    users_repo = PostgresUserRepository(connection=conn)
    refresh_repo = PostgresRefreshSessionRepository(connection=conn)
    players_repo = PostgresPlayerRepository(connection=conn)
    matches_repo = PostgresMatchRepository(connection=conn)
    teams_repo = PostgresTeamRepository(connection=conn)
    videos_repo = PostgresVideoRepository(connection=conn)
    clip_collections_repo = PostgresClipCollectionRepository(connection=conn)
    jobs_repo = PostgresJobRepository(connection=conn)
    video_lookup = PostgresVideoLookup(connection=conn)
    processing_service = build_processing_service()
    video_storage = R2Storage()
    artifact_urls = (
        R2ArtifactUrls(storage=video_storage)
        if video_storage.is_configured
        else UnavailableArtifactUrls()
    )
    artifact_reader = (
        R2ArtifactReader(storage=video_storage)
        if video_storage.is_configured
        else UnavailableArtifactReader()
    )
    team_access = TeamOwnershipAccessAdapter(teams=teams_repo)
    clip_exporter = FFmpegClipExporter(storage=video_storage)
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
    add_clip_batch_use_case = AddClipBatchUseCase(
        collections=clip_collections_repo,
        videos=videos_repo,
        ids=ids,
        uow=uow,
    )

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
        get_player_stats_use_case=GetPlayerStatsUseCase(players=players_repo),
        get_player_matches_use_case=GetPlayerMatchesUseCase(matches=matches_repo, players=players_repo),
        list_players_use_case=ListPlayersUseCase(players=players_repo),
        list_players_by_team_use_case=ListPlayersByTeamUseCase(players=players_repo),
        update_player_use_case=UpdatePlayerUseCase(players=players_repo, uow=uow),
        delete_player_use_case=DeletePlayerUseCase(players=players_repo, uow=uow),
        assign_player_team_use_case=AssignPlayerTeamUseCase(
            players=players_repo,
            teams=teams_repo,
            uow=uow,
        ),
        create_match_use_case=CreateMatchUseCase(matches=matches_repo, teams=teams_repo, ids=ids, uow=uow),
        list_matches_use_case=ListMatchesUseCase(matches=matches_repo, teams=teams_repo),
        get_match_use_case=GetMatchUseCase(matches=matches_repo),
        replace_match_stats_use_case=ReplaceMatchStatsUseCase(matches=matches_repo, players=players_repo, ids=ids, uow=uow),
        get_match_stats_use_case=GetMatchStatsUseCase(matches=matches_repo),
        get_team_stats_use_case=GetTeamStatsUseCase(matches=matches_repo, teams=teams_repo),
        init_video_upload_use_case=InitVideoUploadUseCase(
            videos=videos_repo,
            storage=video_storage,
            team_access=team_access,
            ids=ids,
            uow=uow,
        ),
        complete_video_upload_use_case=CompleteVideoUploadUseCase(
            videos=videos_repo,
            storage=video_storage,
            team_access=team_access,
            uow=uow,
        ),
        abort_video_upload_use_case=AbortVideoUploadUseCase(
            videos=videos_repo,
            storage=video_storage,
            team_access=team_access,
            uow=uow,
        ),
        list_videos_use_case=ListVideosUseCase(videos=videos_repo, team_access=team_access),
        get_video_use_case=GetVideoUseCase(
            videos=videos_repo,
            storage=video_storage,
            team_access=team_access,
        ),
        update_video_use_case=UpdateVideoUseCase(
            videos=videos_repo,
            team_access=team_access,
            uow=uow,
        ),
        delete_video_use_case=DeleteVideoUseCase(
            videos=videos_repo,
            storage=video_storage,
            team_access=team_access,
            uow=uow,
        ),
        create_clip_collection_use_case=CreateClipCollectionUseCase(
            collections=clip_collections_repo,
            videos=videos_repo,
            ids=ids,
            uow=uow,
        ),
        list_clip_collections_use_case=ListClipCollectionsUseCase(
            collections=clip_collections_repo,
            videos=videos_repo,
        ),
        get_clip_collection_detail_use_case=GetClipCollectionDetailUseCase(
            collections=clip_collections_repo,
            videos=videos_repo,
        ),
        add_clip_batch_use_case=add_clip_batch_use_case,
        add_clip_use_case=AddClipUseCase(batch_use_case=add_clip_batch_use_case),
        delete_clip_collection_item_use_case=DeleteClipCollectionItemUseCase(
            collections=clip_collections_repo,
            videos=videos_repo,
            uow=uow,
        ),
        submit_processing_job_use_case=SubmitProcessingJobUseCase(
            jobs=jobs_repo,
            videos=video_lookup,
            processing=processing_service,
            team_access=team_access,
            ids=ids,
            uow=uow,
        ),
        get_processing_job_use_case=GetProcessingJobUseCase(
            jobs=jobs_repo,
            team_access=team_access,
        ),
        list_video_jobs_use_case=ListVideoJobsUseCase(
            jobs=jobs_repo,
            team_access=team_access,
        ),
        record_job_progress_use_case=RecordJobProgressUseCase(jobs=jobs_repo, uow=uow),
        get_job_results_use_case=GetJobResultsUseCase(
            jobs=jobs_repo,
            urls=artifact_urls,
            team_access=team_access,
        ),
        processing_callback_token=(os.getenv("PROCESSING_CALLBACK_TOKEN") or "").strip(),
        game_stats_use_case=GetGameStatsUseCase(
            jobs=jobs_repo, artifacts=artifact_reader, team_access=team_access
        ),
        court_positions_use_case=GetCourtPositionsUseCase(
            jobs=jobs_repo, artifacts=artifact_reader, team_access=team_access
        ),
        export_clip_item_use_case=ExportClipItemUseCase(
            collections=clip_collections_repo,
            videos=videos_repo,
            exporter=clip_exporter,
        ),
        access_token_resolver=access_token_resolver,
    )
