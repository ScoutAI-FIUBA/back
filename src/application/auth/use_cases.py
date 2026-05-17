from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from src.application.auth.errors import (
    AUTH_REFRESH_REUSED,
    AUTH_TOKEN_INVALID,
    AUTH_UNAUTHORIZED,
    AUTH_EMAIL_ALREADY_EXISTS,
    AUTH_INVALID_CREDENTIALS,
    AUTH_VALIDATION_ERROR,
    AuthError,
)
from src.application.auth.ports import (
    ClockPort,
    IdGeneratorPort,
    PasswordHasherPort,
    RefreshSessionRepositoryPort,
    RefreshTokenServicePort,
    TokenIssuerPort,
    UnitOfWorkPort,
    UserRepositoryPort,
)
from src.domain.auth.entities import RefreshSession, User
from src.domain.auth.value_objects import AuthIdentity, Email, PlainPassword, TokenPair

ACCESS_TOKEN_TTL_SECONDS = 15 * 60
REFRESH_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class RegisterUserCommand:
    email: str
    password: str


@dataclass(frozen=True)
class LoginCommand:
    email: str
    password: str


@dataclass(frozen=True)
class LoginResult:
    user: AuthIdentity
    tokens: TokenPair


@dataclass(frozen=True)
class RefreshSessionCommand:
    refresh_token: str


@dataclass(frozen=True)
class LogoutCommand:
    refresh_token: str


@dataclass(frozen=True)
class GetCurrentUserQuery:
    user_id: str


@dataclass(frozen=True)
class DeleteCurrentUserCommand:
    user_id: str


@dataclass(frozen=True)
class HardDeleteUserCommand:
    user_id: str


class RegisterUserUseCase:
    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        password_hasher: PasswordHasherPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._users = users
        self._password_hasher = password_hasher
        self._clock = clock
        self._ids = ids
        self._uow = uow

    def execute(self, command: RegisterUserCommand) -> AuthIdentity:
        try:
            email_normalized = Email(command.email).value
            plain_password = PlainPassword(command.password).value
        except ValueError as exc:
            raise AuthError(
                code=AUTH_VALIDATION_ERROR,
                message="Invalid registration payload",
                details={"reason": str(exc)},
            ) from exc

        with self._uow.transaction():
            if self._users.get_by_email(email_normalized) is not None:
                raise AuthError(
                    code=AUTH_EMAIL_ALREADY_EXISTS,
                    message="Email already registered",
                )

            now = self._clock.now()
            created = self._users.create(
                User(
                    id=self._ids.new_id(),
                    email_normalized=email_normalized,
                    password_hash=self._password_hasher.hash(plain_password),
                    email_verified=False,
                    role="user",
                    auth_provider_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return AuthIdentity(
            user_id=created.id,
            email=created.email_normalized,
            role=created.role,
            email_verified=created.email_verified,
        )


class LoginUseCase:
    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        refresh_sessions: RefreshSessionRepositoryPort,
        password_hasher: PasswordHasherPort,
        token_issuer: TokenIssuerPort,
        refresh_tokens: RefreshTokenServicePort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        uow: UnitOfWorkPort,
        access_token_ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS,
        refresh_token_ttl_seconds: int = REFRESH_TOKEN_TTL_SECONDS,
    ) -> None:
        self._users = users
        self._refresh_sessions = refresh_sessions
        self._password_hasher = password_hasher
        self._token_issuer = token_issuer
        self._refresh_tokens = refresh_tokens
        self._clock = clock
        self._ids = ids
        self._uow = uow
        self._access_ttl = access_token_ttl_seconds
        self._refresh_ttl = refresh_token_ttl_seconds

    def execute(self, command: LoginCommand) -> LoginResult:
        email_normalized = Email(command.email).value
        user = self._users.get_by_email(email_normalized)
        if (
            user is None
            or user.deleted_at is not None
            or not self._password_hasher.verify(command.password, user.password_hash)
        ):
            raise AuthError(
                code=AUTH_INVALID_CREDENTIALS,
                message="Invalid credentials",
            )

        now = self._clock.now()
        access_jti = self._ids.new_jti()
        identity = AuthIdentity(
            user_id=user.id,
            email=user.email_normalized,
            role=user.role,
            email_verified=user.email_verified,
        )
        access_token = self._token_issuer.issue_access(
            identity=identity,
            jti=access_jti,
            expires_at=now + timedelta(seconds=self._access_ttl),
        )

        refresh_plain = self._refresh_tokens.generate_plain()
        refresh_hash = self._refresh_tokens.hash(refresh_plain)

        with self._uow.transaction():
            self._refresh_sessions.create(
                RefreshSession(
                    id=self._ids.new_id(),
                    user_id=user.id,
                    token_hash=refresh_hash,
                    token_jti=self._ids.new_jti(),
                    family_id=self._ids.new_family_id(),
                    issued_at=now,
                    expires_at=now + timedelta(seconds=self._refresh_ttl),
                )
            )

        return LoginResult(
            user=identity,
            tokens=TokenPair(
                access_token=access_token,
                refresh_token=refresh_plain,
                token_type="Bearer",
                expires_in=self._access_ttl,
            ),
        )


class RefreshSessionUseCase:
    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        refresh_sessions: RefreshSessionRepositoryPort,
        token_issuer: TokenIssuerPort,
        refresh_tokens: RefreshTokenServicePort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        uow: UnitOfWorkPort,
        access_token_ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS,
        refresh_token_ttl_seconds: int = REFRESH_TOKEN_TTL_SECONDS,
    ) -> None:
        self._users = users
        self._refresh_sessions = refresh_sessions
        self._token_issuer = token_issuer
        self._refresh_tokens = refresh_tokens
        self._clock = clock
        self._ids = ids
        self._uow = uow
        self._access_ttl = access_token_ttl_seconds
        self._refresh_ttl = refresh_token_ttl_seconds

    def execute(self, command: RefreshSessionCommand) -> LoginResult:
        now = self._clock.now()
        presented_hash = self._refresh_tokens.hash(command.refresh_token)
        session = self._refresh_sessions.get_active_by_token_hash(presented_hash, now)

        if session is None:
            known_session = self._refresh_sessions.get_by_token_hash(presented_hash)
            if known_session is not None:
                with self._uow.transaction():
                    self._refresh_sessions.mark_reuse_detected(known_session.id, now)
                    self._refresh_sessions.revoke_family(known_session.family_id, now)
                raise AuthError(code=AUTH_REFRESH_REUSED, message="Refresh token reuse detected")

            raise AuthError(code=AUTH_TOKEN_INVALID, message="Refresh token is invalid")

        user = self._users.get_by_id(session.user_id)
        if user is None:
            raise AuthError(code=AUTH_UNAUTHORIZED, message="User not found")

        identity = AuthIdentity(
            user_id=user.id,
            email=user.email_normalized,
            role=user.role,
            email_verified=user.email_verified,
        )
        access_token = self._token_issuer.issue_access(
            identity=identity,
            jti=self._ids.new_jti(),
            expires_at=now + timedelta(seconds=self._access_ttl),
        )
        refresh_plain = self._refresh_tokens.generate_plain()
        next_session = RefreshSession(
            id=self._ids.new_id(),
            user_id=user.id,
            token_hash=self._refresh_tokens.hash(refresh_plain),
            token_jti=self._ids.new_jti(),
            family_id=session.family_id,
            issued_at=now,
            expires_at=now + timedelta(seconds=self._refresh_ttl),
        )

        with self._uow.transaction():
            rotated = self._refresh_sessions.rotate(
                old_session_id=session.id,
                new_session=next_session,
                revoked_at=now,
            )
            if rotated is None:
                raise AuthError(code=AUTH_REFRESH_REUSED, message="Refresh token reuse detected")

        return LoginResult(
            user=identity,
            tokens=TokenPair(
                access_token=access_token,
                refresh_token=refresh_plain,
                token_type="Bearer",
                expires_in=self._access_ttl,
            ),
        )


class LogoutUseCase:
    def __init__(
        self,
        *,
        refresh_sessions: RefreshSessionRepositoryPort,
        refresh_tokens: RefreshTokenServicePort,
        clock: ClockPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._refresh_sessions = refresh_sessions
        self._refresh_tokens = refresh_tokens
        self._clock = clock
        self._uow = uow

    def execute(self, command: LogoutCommand) -> None:
        token_hash = self._refresh_tokens.hash(command.refresh_token)
        session = self._refresh_sessions.get_by_token_hash(token_hash)
        if session is None:
            return
        with self._uow.transaction():
            self._refresh_sessions.revoke(session.id, self._clock.now())


class GetCurrentUserUseCase:
    def __init__(self, *, users: UserRepositoryPort) -> None:
        self._users = users

    def execute(self, query: GetCurrentUserQuery) -> AuthIdentity:
        user = self._users.get_by_id(query.user_id)
        if user is None or user.deleted_at is not None:
            raise AuthError(code=AUTH_UNAUTHORIZED, message="User not found")
        return AuthIdentity(
            user_id=user.id,
            email=user.email_normalized,
            role=user.role,
            email_verified=user.email_verified,
        )


class DeleteCurrentUserUseCase:
    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        refresh_sessions: RefreshSessionRepositoryPort,
        clock: ClockPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._users = users
        self._refresh_sessions = refresh_sessions
        self._clock = clock
        self._uow = uow

    def execute(self, command: DeleteCurrentUserCommand) -> None:
        now = self._clock.now()
        with self._uow.transaction():
            deleted = self._users.soft_delete(command.user_id, now)
            if deleted is None:
                raise AuthError(code=AUTH_UNAUTHORIZED, message="User not found")
            self._refresh_sessions.revoke_all_by_user_id(command.user_id, now)


class HardDeleteUserUseCase:
    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        refresh_sessions: RefreshSessionRepositoryPort,
        clock: ClockPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._users = users
        self._refresh_sessions = refresh_sessions
        self._clock = clock
        self._uow = uow

    def execute(self, command: HardDeleteUserCommand) -> None:
        with self._uow.transaction():
            self._refresh_sessions.revoke_all_by_user_id(command.user_id, self._clock.now())
            self._users.hard_delete(command.user_id)
