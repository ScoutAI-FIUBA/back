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
    ChangePasswordUseCase,
    ConfirmEmailVerificationUseCase,
    DeleteCurrentUserUseCase,
    GetCurrentUserUseCase,
    GoogleLoginUseCase,
    HardDeleteUserUseCase,
    LoginUseCase,
    LogoutUseCase,
    RefreshSessionUseCase,
    RegisterUserUseCase,
    RequestPasswordResetUseCase,
    ResetPasswordUseCase,
    SendEmailVerificationUseCase,
    UpdateProfileUseCase,
)
from src.application.clip_collections.use_cases import (
    AddClipBatchUseCase,
    AddClipUseCase,
    CreateClipCollectionUseCase,
    DeleteClipCollectionItemUseCase,
    ExportClipItemUseCase,
    GetClipCollectionDetailUseCase,
    ListClipCollectionsUseCase,
    UpdateClipDescriptionUseCase,
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
    SetJobTeamSideUseCase,
    SubmitProcessingJobUseCase,
)
from src.application.stats.use_cases import (
    GetCourtPositionsUseCase,
    GetGameStatsUseCase,
    GetShotChartUseCase,
    GetSimilarClipsUseCase,
    GetTeamSidesUseCase,
)
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
from src.infrastructure.auth.google_id_token_verifier import (
    GoogleIdTokenVerifier,
    UnconfiguredGoogleIdTokenVerifier,
)
from src.infrastructure.auth.jwt_access_token_resolver import JWTAccessTokenResolver
from src.infrastructure.auth.jwt_token_issuer import JWTTokenIssuer
from src.infrastructure.auth.opaque_refresh_token_service import OpaqueRefreshTokenService
from src.infrastructure.auth.postgres_repositories import (
    PostgresEmailTokenRepository,
    PostgresRefreshSessionRepository,
    PostgresUserRepository,
)
from src.infrastructure.auth.brevo_email_sender import BrevoEmailSender
from src.infrastructure.auth.resend_email_sender import NoOpEmailSender, ResendEmailSender
from src.infrastructure.auth.smtp_email_sender import SmtpEmailSender
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
from src.infrastructure.video.ffmpeg_thumbnail_generator import FFmpegThumbnailGenerator
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
    request_password_reset_use_case: RequestPasswordResetUseCase
    reset_password_use_case: ResetPasswordUseCase
    change_password_use_case: ChangePasswordUseCase
    update_profile_use_case: UpdateProfileUseCase
    send_email_verification_use_case: SendEmailVerificationUseCase
    confirm_email_verification_use_case: ConfirmEmailVerificationUseCase
    google_login_use_case: GoogleLoginUseCase
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
    update_clip_description_use_case: UpdateClipDescriptionUseCase
    delete_clip_collection_item_use_case: DeleteClipCollectionItemUseCase
    submit_processing_job_use_case: SubmitProcessingJobUseCase
    get_processing_job_use_case: GetProcessingJobUseCase
    list_video_jobs_use_case: ListVideoJobsUseCase
    record_job_progress_use_case: RecordJobProgressUseCase
    get_job_results_use_case: GetJobResultsUseCase
    set_job_team_side_use_case: SetJobTeamSideUseCase
    game_stats_use_case: GetGameStatsUseCase
    court_positions_use_case: GetCourtPositionsUseCase
    shot_chart_use_case: GetShotChartUseCase
    team_sides_use_case: GetTeamSidesUseCase
    similar_clips_use_case: GetSimilarClipsUseCase
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


def _app_public_url() -> str:
    """Front URL used inside password-reset and verification emails.

    Prefer APP_PUBLIC_URL. In production deploys that forget it, fall back to
    the first CORS origin so links do not silently point at localhost.
    """

    explicit = (os.getenv("APP_PUBLIC_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    cors = (os.getenv("CORS_ORIGINS") or "").strip()
    if cors:
        first = cors.split(",")[0].strip().rstrip("/")
        if first:
            return first
    return "http://localhost:5173"


def _build_email_sender():
    # Render blocks outbound SMTP (25/465/587). HTTPS APIs work there.
    # Brevo: verify one sender email by clicking a link, then mail anyone.
    brevo_api_key = (os.getenv("BREVO_API_KEY") or "").strip()
    if brevo_api_key:
        from_address = (
            os.getenv("BREVO_FROM_ADDRESS") or os.getenv("SMTP_FROM_ADDRESS") or ""
        ).strip()
        if not from_address:
            return NoOpEmailSender()
        return BrevoEmailSender(api_key=brevo_api_key, from_address=from_address)
    resend_api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    if resend_api_key:
        return ResendEmailSender(
            api_key=resend_api_key,
            from_address=(os.getenv("RESEND_FROM_ADDRESS") or "ScoutAI <noreply@localhost>").strip(),
        )
    smtp_username = (os.getenv("SMTP_USERNAME") or "").strip()
    smtp_password = (os.getenv("SMTP_PASSWORD") or "").strip()
    if smtp_username and smtp_password:
        return SmtpEmailSender(
            host=(os.getenv("SMTP_HOST") or "smtp.gmail.com").strip(),
            port=int((os.getenv("SMTP_PORT") or "587").strip()),
            username=smtp_username,
            password=smtp_password,
            from_address=(os.getenv("SMTP_FROM_ADDRESS") or smtp_username).strip(),
        )
    return NoOpEmailSender()


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
    email_tokens_repo = PostgresEmailTokenRepository(connection=conn)
    email_sender = _build_email_sender()
    app_public_url = _app_public_url()
    google_client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    google_verifier = (
        GoogleIdTokenVerifier(client_id=google_client_id)
        if google_client_id
        else UnconfiguredGoogleIdTokenVerifier()
    )
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
    thumbnail_generator = FFmpegThumbnailGenerator(storage=video_storage)
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
        request_password_reset_use_case=RequestPasswordResetUseCase(
            users=users_repo,
            email_tokens=email_tokens_repo,
            email_sender=email_sender,
            refresh_tokens=refresh_tokens,
            clock=clock,
            ids=ids,
            uow=uow,
            app_public_url=app_public_url,
        ),
        reset_password_use_case=ResetPasswordUseCase(
            users=users_repo,
            email_tokens=email_tokens_repo,
            refresh_sessions=refresh_repo,
            password_hasher=password_hasher,
            refresh_tokens=refresh_tokens,
            clock=clock,
            uow=uow,
        ),
        change_password_use_case=ChangePasswordUseCase(
            users=users_repo,
            refresh_sessions=refresh_repo,
            password_hasher=password_hasher,
            clock=clock,
            uow=uow,
        ),
        update_profile_use_case=UpdateProfileUseCase(users=users_repo, clock=clock, uow=uow),
        send_email_verification_use_case=SendEmailVerificationUseCase(
            users=users_repo,
            email_tokens=email_tokens_repo,
            email_sender=email_sender,
            refresh_tokens=refresh_tokens,
            clock=clock,
            ids=ids,
            uow=uow,
            app_public_url=app_public_url,
        ),
        confirm_email_verification_use_case=ConfirmEmailVerificationUseCase(
            users=users_repo,
            email_tokens=email_tokens_repo,
            refresh_tokens=refresh_tokens,
            clock=clock,
            uow=uow,
        ),
        google_login_use_case=GoogleLoginUseCase(
            users=users_repo,
            refresh_sessions=refresh_repo,
            password_hasher=password_hasher,
            token_issuer=token_issuer,
            refresh_tokens=refresh_tokens,
            verifier=google_verifier,
            clock=clock,
            ids=ids,
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
            thumbnail_generator=thumbnail_generator,
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
            thumbnail_generator=thumbnail_generator,
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
        update_clip_description_use_case=UpdateClipDescriptionUseCase(
            collections=clip_collections_repo,
            videos=videos_repo,
            uow=uow,
        ),
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
        set_job_team_side_use_case=SetJobTeamSideUseCase(
            jobs=jobs_repo,
            team_access=team_access,
        ),
        processing_callback_token=(os.getenv("PROCESSING_CALLBACK_TOKEN") or "").strip(),
        game_stats_use_case=GetGameStatsUseCase(
            jobs=jobs_repo, artifacts=artifact_reader, team_access=team_access, roster=players_repo
        ),
        court_positions_use_case=GetCourtPositionsUseCase(
            jobs=jobs_repo, artifacts=artifact_reader, team_access=team_access
        ),
        export_clip_item_use_case=ExportClipItemUseCase(
            collections=clip_collections_repo,
            videos=videos_repo,
            exporter=clip_exporter,
        ),
        shot_chart_use_case=GetShotChartUseCase(
            jobs=jobs_repo, artifacts=artifact_reader, team_access=team_access, roster=players_repo
        ),
        team_sides_use_case=GetTeamSidesUseCase(
            jobs=jobs_repo, artifacts=artifact_reader, team_access=team_access, roster=players_repo
        ),
        similar_clips_use_case=GetSimilarClipsUseCase(
            jobs=jobs_repo, artifacts=artifact_reader, team_access=team_access
        ),
        access_token_resolver=access_token_resolver,
    )
