from __future__ import annotations

"""Application-layer auth use cases and command/query contracts.

These classes orchestrate domain operations through ports and keep HTTP/database
concerns outside the application layer.
"""

from dataclasses import dataclass
from datetime import timedelta
import logging

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
    AuthIdGeneratorPort,
    ClockPort,
    EmailSenderPort,
    EmailTokenRepositoryPort,
    GoogleIdTokenVerifierPort,
    PasswordHasherPort,
    RefreshSessionRepositoryPort,
    RefreshTokenServicePort,
    TokenIssuerPort,
    UnitOfWorkPort,
    UserRepositoryPort,
)
from src.domain.auth.entities import (
    EMAIL_VERIFICATION,
    PASSWORD_RESET,
    EmailToken,
    RefreshSession,
    User,
)
from src.domain.auth.value_objects import AuthIdentity, Email, PlainPassword, TokenPair

logger = logging.getLogger(__name__)

ACCESS_TOKEN_TTL_SECONDS = 15 * 60
REFRESH_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60
PASSWORD_RESET_TTL_SECONDS = 60 * 60
EMAIL_VERIFICATION_TTL_SECONDS = 24 * 60 * 60
EMAIL_TOKEN_HOURLY_LIMIT = 10


def _identity(user: User) -> AuthIdentity:
    return AuthIdentity(
        user_id=user.id,
        email=user.email_normalized,
        role=user.role,
        email_verified=user.email_verified,
        full_name=user.full_name,
    )


@dataclass(frozen=True)
class RegisterUserCommand:
    """Registration payload accepted by ``RegisterUserUseCase``."""

    email: str
    password: str
    full_name: str | None = None


@dataclass(frozen=True)
class LoginCommand:
    """Credential payload used by ``LoginUseCase``."""

    email: str
    password: str


@dataclass(frozen=True)
class LoginResult:
    """Auth response contract returned by login/refresh flows."""

    user: AuthIdentity
    tokens: TokenPair


@dataclass(frozen=True)
class RefreshSessionCommand:
    """Refresh cookie payload used to rotate refresh sessions."""

    refresh_token: str


@dataclass(frozen=True)
class LogoutCommand:
    """Logout payload carrying the presented refresh token."""

    refresh_token: str


@dataclass(frozen=True)
class GetCurrentUserQuery:
    """Identity lookup query scoped to an authenticated user id."""

    user_id: str


@dataclass(frozen=True)
class DeleteCurrentUserCommand:
    """Soft-delete request scoped to the authenticated user id."""

    user_id: str


@dataclass(frozen=True)
class HardDeleteUserCommand:
    """Hard-delete request scoped to a concrete user id."""

    user_id: str


class RegisterUserUseCase:
    """Registers local credentials and persists the user in one transaction.

    Uniqueness is enforced by checking email existence inside the same unit of
    work used for insert.
    """

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        password_hasher: PasswordHasherPort,
        clock: ClockPort,
        ids: AuthIdGeneratorPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._users = users
        self._password_hasher = password_hasher
        self._clock = clock
        self._ids = ids
        self._uow = uow

    def execute(self, command: RegisterUserCommand) -> AuthIdentity:
        """Validates input and persists one new local user atomically.

        Error mapping:
        - malformed email/password -> AUTH_VALIDATION_ERROR
        - duplicate normalized email -> AUTH_EMAIL_ALREADY_EXISTS
        """

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
                    full_name=_normalize_full_name(command.full_name),
                    created_at=now,
                    updated_at=now,
                )
            )
        return _identity(created)


class LoginUseCase:
    """Authenticates a non-deleted user and creates a refresh-session family root."""

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        refresh_sessions: RefreshSessionRepositoryPort,
        password_hasher: PasswordHasherPort,
        token_issuer: TokenIssuerPort,
        refresh_tokens: RefreshTokenServicePort,
        clock: ClockPort,
        ids: AuthIdGeneratorPort,
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
        """Returns issued tokens and identity for valid credentials.

        Raises:
            AuthError: AUTH_INVALID_CREDENTIALS when user is missing, soft-deleted,
                or password verification fails.
        """

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
        identity = _identity(user)
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
    """Rotates refresh tokens with one-time-use and family-revocation semantics."""

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        refresh_sessions: RefreshSessionRepositoryPort,
        token_issuer: TokenIssuerPort,
        refresh_tokens: RefreshTokenServicePort,
        clock: ClockPort,
        ids: AuthIdGeneratorPort,
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
        """Rotates one active refresh session and issues a new token pair.

        If a known-but-inactive token is presented, marks reuse on that session
        and revokes the full family in the same transaction.

        Raises:
            AuthError: AUTH_REFRESH_REUSED when reuse is detected or rotation loses
                a revoke/replace race; AUTH_TOKEN_INVALID for unknown tokens;
                AUTH_UNAUTHORIZED when the session user no longer exists.
        """

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

        identity = _identity(user)
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
    """Best-effort refresh-session revocation.

    Missing/unknown tokens are treated as no-op to keep logout idempotent.
    """

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
        """Revokes the presented refresh session when known.

        Invariant: logout stays idempotent, so unknown or already-removed tokens
        intentionally produce no error.
        """

        token_hash = self._refresh_tokens.hash(command.refresh_token)
        session = self._refresh_sessions.get_by_token_hash(token_hash)
        if session is None:
            return
        with self._uow.transaction():
            self._refresh_sessions.revoke(session.id, self._clock.now())


class GetCurrentUserUseCase:
    """Loads current identity for an authenticated principal.

    Soft-deleted users are treated as unauthorized.
    """

    def __init__(self, *, users: UserRepositoryPort) -> None:
        self._users = users

    def execute(self, query: GetCurrentUserQuery) -> AuthIdentity:
        """Returns current user identity or AUTH_UNAUTHORIZED when unavailable."""

        user = self._users.get_by_id(query.user_id)
        if user is None or user.deleted_at is not None:
            raise AuthError(code=AUTH_UNAUTHORIZED, message="User not found")
        return _identity(user)


class DeleteCurrentUserUseCase:
    """Soft-deletes the user and revokes all active refresh sessions atomically."""

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
        """Soft-deletes the account and revokes all refresh sessions atomically."""

        now = self._clock.now()
        with self._uow.transaction():
            deleted = self._users.soft_delete(command.user_id, now)
            if deleted is None:
                raise AuthError(code=AUTH_UNAUTHORIZED, message="User not found")
            self._refresh_sessions.revoke_all_by_user_id(command.user_id, now)


class HardDeleteUserUseCase:
    """Hard-deletes the user and revokes active refresh sessions atomically.

    Revocation happens before delete inside the same transaction to avoid leaving
    active sessions for a removed account.
    """

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
        """Hard-deletes a user while revoking live refresh sessions first."""

        with self._uow.transaction():
            self._refresh_sessions.revoke_all_by_user_id(command.user_id, self._clock.now())
            self._users.hard_delete(command.user_id)


def _normalize_full_name(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    return text[:120] or None


def _issue_session(
    *,
    user: User,
    token_issuer: TokenIssuerPort,
    refresh_tokens: RefreshTokenServicePort,
    refresh_sessions: RefreshSessionRepositoryPort,
    clock: ClockPort,
    ids: AuthIdGeneratorPort,
    uow: UnitOfWorkPort,
    access_ttl: int,
    refresh_ttl: int,
) -> LoginResult:
    now = clock.now()
    identity = _identity(user)
    access_token = token_issuer.issue_access(
        identity=identity,
        jti=ids.new_jti(),
        expires_at=now + timedelta(seconds=access_ttl),
    )
    refresh_plain = refresh_tokens.generate_plain()
    with uow.transaction():
        refresh_sessions.create(
            RefreshSession(
                id=ids.new_id(),
                user_id=user.id,
                token_hash=refresh_tokens.hash(refresh_plain),
                token_jti=ids.new_jti(),
                family_id=ids.new_family_id(),
                issued_at=now,
                expires_at=now + timedelta(seconds=refresh_ttl),
            )
        )
    return LoginResult(
        user=identity,
        tokens=TokenPair(
            access_token=access_token,
            refresh_token=refresh_plain,
            token_type="Bearer",
            expires_in=access_ttl,
        ),
    )


@dataclass(frozen=True)
class RequestPasswordResetCommand:
    email: str


@dataclass(frozen=True)
class ResetPasswordCommand:
    token: str
    password: str


@dataclass(frozen=True)
class ChangePasswordCommand:
    user_id: str
    current_password: str
    new_password: str


@dataclass(frozen=True)
class UpdateProfileCommand:
    user_id: str
    full_name: str


@dataclass(frozen=True)
class SendEmailVerificationCommand:
    user_id: str


@dataclass(frozen=True)
class ConfirmEmailVerificationCommand:
    token: str


@dataclass(frozen=True)
class GoogleLoginCommand:
    id_token: str


class RequestPasswordResetUseCase:
    """Accepts a reset request and emails a one-time link when the account exists.

    Always succeeds from the caller's point of view so the endpoint cannot be
    used to enumerate registered emails. Rate-limited accounts are treated the
    same way: no mail goes out, no error is raised.
    """

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        email_tokens: EmailTokenRepositoryPort,
        email_sender: EmailSenderPort,
        refresh_tokens: RefreshTokenServicePort,
        clock: ClockPort,
        ids: AuthIdGeneratorPort,
        uow: UnitOfWorkPort,
        app_public_url: str,
    ) -> None:
        self._users = users
        self._email_tokens = email_tokens
        self._email_sender = email_sender
        self._refresh_tokens = refresh_tokens
        self._clock = clock
        self._ids = ids
        self._uow = uow
        self._app_public_url = app_public_url.rstrip("/")

    def execute(self, command: RequestPasswordResetCommand) -> None:
        try:
            email_normalized = Email(command.email).value
        except ValueError:
            return
        user = self._users.get_by_email(email_normalized)
        if user is None or user.deleted_at is not None:
            return
        now = self._clock.now()
        if self._email_tokens.count_recent(user.id, PASSWORD_RESET, now - timedelta(hours=1)) >= EMAIL_TOKEN_HOURLY_LIMIT:
            logger.info("Password reset throttled for user_id=%s", user.id)
            return
        plain = self._refresh_tokens.generate_plain()
        token = EmailToken(
            id=self._ids.new_id(),
            user_id=user.id,
            purpose=PASSWORD_RESET,
            token_hash=self._refresh_tokens.hash(plain),
            created_at=now,
            expires_at=now + timedelta(seconds=PASSWORD_RESET_TTL_SECONDS),
        )
        with self._uow.transaction():
            self._email_tokens.create(token)
        reset_url = f"{self._app_public_url}/restablecer-password?token={plain}"
        try:
            self._email_sender.send(
                to=user.email_normalized,
                subject="Restablecé tu contraseña de ScoutAI",
                html=(
                    "<p>Recibimos un pedido para restablecer tu contraseña.</p>"
                    f'<p><a href="{reset_url}">Elegí una contraseña nueva</a></p>'
                    "<p>El enlace vence en una hora. Si no fuiste vos, ignorá este mail.</p>"
                ),
            )
        except AuthError:
            logger.exception("Password reset email was not sent")
            with self._uow.transaction():
                self._email_tokens.delete(token.id)

class ResetPasswordUseCase:
    """Redeems a password-reset token and invalidates every refresh session."""

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        email_tokens: EmailTokenRepositoryPort,
        refresh_sessions: RefreshSessionRepositoryPort,
        password_hasher: PasswordHasherPort,
        refresh_tokens: RefreshTokenServicePort,
        clock: ClockPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._users = users
        self._email_tokens = email_tokens
        self._refresh_sessions = refresh_sessions
        self._password_hasher = password_hasher
        self._refresh_tokens = refresh_tokens
        self._clock = clock
        self._uow = uow

    def execute(self, command: ResetPasswordCommand) -> None:
        try:
            plain_password = PlainPassword(command.password).value
        except ValueError as exc:
            raise AuthError(
                code=AUTH_VALIDATION_ERROR,
                message="Invalid password",
                details={"reason": str(exc)},
            ) from exc
        now = self._clock.now()
        token = self._email_tokens.get_usable_by_hash(
            self._refresh_tokens.hash(command.token),
            PASSWORD_RESET,
            now,
        )
        if token is None:
            raise AuthError(code=AUTH_TOKEN_INVALID, message="Reset token is invalid or expired")
        with self._uow.transaction():
            updated = self._users.update_password_hash(
                token.user_id,
                self._password_hasher.hash(plain_password),
                now,
            )
            if updated is None:
                raise AuthError(code=AUTH_UNAUTHORIZED, message="User not found")
            self._email_tokens.mark_used(token.id, now)
            self._refresh_sessions.revoke_all_by_user_id(token.user_id, now)


class ChangePasswordUseCase:
    """Changes the password of an authenticated user and revokes other sessions."""

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        refresh_sessions: RefreshSessionRepositoryPort,
        password_hasher: PasswordHasherPort,
        clock: ClockPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._users = users
        self._refresh_sessions = refresh_sessions
        self._password_hasher = password_hasher
        self._clock = clock
        self._uow = uow

    def execute(self, command: ChangePasswordCommand) -> None:
        try:
            new_password = PlainPassword(command.new_password).value
        except ValueError as exc:
            raise AuthError(
                code=AUTH_VALIDATION_ERROR,
                message="Invalid password",
                details={"reason": str(exc)},
            ) from exc
        user = self._users.get_by_id(command.user_id)
        if user is None or user.deleted_at is not None:
            raise AuthError(code=AUTH_UNAUTHORIZED, message="User not found")
        if not self._password_hasher.verify(command.current_password, user.password_hash):
            raise AuthError(code=AUTH_INVALID_CREDENTIALS, message="Current password is incorrect")
        if command.current_password == new_password:
            raise AuthError(code=AUTH_VALIDATION_ERROR, message="New password must be different")
        now = self._clock.now()
        with self._uow.transaction():
            self._users.update_password_hash(user.id, self._password_hasher.hash(new_password), now)
            self._refresh_sessions.revoke_all_by_user_id(user.id, now)


class UpdateProfileUseCase:
    """Updates the authenticated user's display name."""

    def __init__(self, *, users: UserRepositoryPort, clock: ClockPort, uow: UnitOfWorkPort) -> None:
        self._users = users
        self._clock = clock
        self._uow = uow

    def execute(self, command: UpdateProfileCommand) -> AuthIdentity:
        full_name = _normalize_full_name(command.full_name)
        if full_name is None:
            raise AuthError(code=AUTH_VALIDATION_ERROR, message="Full name is required")
        with self._uow.transaction():
            updated = self._users.update_profile(command.user_id, full_name, self._clock.now())
        if updated is None:
            raise AuthError(code=AUTH_UNAUTHORIZED, message="User not found")
        return _identity(updated)


class SendEmailVerificationUseCase:
    """Emails a verification link to the authenticated user."""

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        email_tokens: EmailTokenRepositoryPort,
        email_sender: EmailSenderPort,
        refresh_tokens: RefreshTokenServicePort,
        clock: ClockPort,
        ids: AuthIdGeneratorPort,
        uow: UnitOfWorkPort,
        app_public_url: str,
    ) -> None:
        self._users = users
        self._email_tokens = email_tokens
        self._email_sender = email_sender
        self._refresh_tokens = refresh_tokens
        self._clock = clock
        self._ids = ids
        self._uow = uow
        self._app_public_url = app_public_url.rstrip("/")

    def execute(self, command: SendEmailVerificationCommand) -> None:
        user = self._users.get_by_id(command.user_id)
        if user is None or user.deleted_at is not None:
            raise AuthError(code=AUTH_UNAUTHORIZED, message="User not found")
        if user.email_verified:
            return
        now = self._clock.now()
        if (
            self._email_tokens.count_recent(user.id, EMAIL_VERIFICATION, now - timedelta(hours=1))
            >= EMAIL_TOKEN_HOURLY_LIMIT
        ):
            raise AuthError(code="AUTH_RATE_LIMITED", message="Too many verification emails")
        plain = self._refresh_tokens.generate_plain()
        with self._uow.transaction():
            self._email_tokens.create(
                EmailToken(
                    id=self._ids.new_id(),
                    user_id=user.id,
                    purpose=EMAIL_VERIFICATION,
                    token_hash=self._refresh_tokens.hash(plain),
                    created_at=now,
                    expires_at=now + timedelta(seconds=EMAIL_VERIFICATION_TTL_SECONDS),
                )
            )
        verify_url = f"{self._app_public_url}/verificar-email?token={plain}"
        self._email_sender.send(
            to=user.email_normalized,
            subject="Verificá tu correo de ScoutAI",
            html=(
                "<p>Confirmá que este correo es tuyo.</p>"
                f'<p><a href="{verify_url}">Verificar correo</a></p>'
                "<p>El enlace vence en 24 horas.</p>"
            ),
        )


class ConfirmEmailVerificationUseCase:
    """Marks the account as verified when a valid token is presented."""

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        email_tokens: EmailTokenRepositoryPort,
        refresh_tokens: RefreshTokenServicePort,
        clock: ClockPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._users = users
        self._email_tokens = email_tokens
        self._refresh_tokens = refresh_tokens
        self._clock = clock
        self._uow = uow

    def execute(self, command: ConfirmEmailVerificationCommand) -> AuthIdentity:
        now = self._clock.now()
        token = self._email_tokens.get_usable_by_hash(
            self._refresh_tokens.hash(command.token),
            EMAIL_VERIFICATION,
            now,
        )
        if token is None:
            raise AuthError(code=AUTH_TOKEN_INVALID, message="Verification token is invalid or expired")
        with self._uow.transaction():
            updated = self._users.mark_email_verified(token.user_id, now)
            if updated is None:
                raise AuthError(code=AUTH_UNAUTHORIZED, message="User not found")
            self._email_tokens.mark_used(token.id, now)
        return _identity(updated)


class GoogleLoginUseCase:
    """Logs in or registers a user from a verified Google ID token."""

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        refresh_sessions: RefreshSessionRepositoryPort,
        password_hasher: PasswordHasherPort,
        token_issuer: TokenIssuerPort,
        refresh_tokens: RefreshTokenServicePort,
        verifier: GoogleIdTokenVerifierPort,
        clock: ClockPort,
        ids: AuthIdGeneratorPort,
        uow: UnitOfWorkPort,
        access_token_ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS,
        refresh_token_ttl_seconds: int = REFRESH_TOKEN_TTL_SECONDS,
    ) -> None:
        self._users = users
        self._refresh_sessions = refresh_sessions
        self._password_hasher = password_hasher
        self._token_issuer = token_issuer
        self._refresh_tokens = refresh_tokens
        self._verifier = verifier
        self._clock = clock
        self._ids = ids
        self._uow = uow
        self._access_ttl = access_token_ttl_seconds
        self._refresh_ttl = refresh_token_ttl_seconds

    def execute(self, command: GoogleLoginCommand) -> LoginResult:
        claims = self._verifier.verify(command.id_token)
        email_normalized = Email(claims.email).value
        now = self._clock.now()
        provider_id = f"google:{claims.subject}"
        user = self._users.get_by_email(email_normalized)
        if user is not None and user.deleted_at is not None:
            raise AuthError(code=AUTH_UNAUTHORIZED, message="User not found")
        with self._uow.transaction():
            if user is None:
                user = self._users.create(
                    User(
                        id=self._ids.new_id(),
                        email_normalized=email_normalized,
                        password_hash=self._password_hasher.hash(self._refresh_tokens.generate_plain()),
                        email_verified=True,
                        role="user",
                        auth_provider_id=provider_id,
                        full_name=_normalize_full_name(claims.full_name),
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                if user.auth_provider_id != provider_id:
                    user = self._users.set_auth_provider(user.id, provider_id, now) or user
                if claims.email_verified and not user.email_verified:
                    user = self._users.mark_email_verified(user.id, now) or user
        return _issue_session(
            user=user,
            token_issuer=self._token_issuer,
            refresh_tokens=self._refresh_tokens,
            refresh_sessions=self._refresh_sessions,
            clock=self._clock,
            ids=self._ids,
            uow=self._uow,
            access_ttl=self._access_ttl,
            refresh_ttl=self._refresh_ttl,
        )
