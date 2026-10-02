from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import unittest

from src.application.auth.errors import AUTH_INVALID_CREDENTIALS, AUTH_TOKEN_INVALID, AuthError
from src.application.auth.ports import GoogleIdentity
from src.application.auth.use_cases import (
    ChangePasswordCommand,
    ChangePasswordUseCase,
    ConfirmEmailVerificationCommand,
    ConfirmEmailVerificationUseCase,
    GoogleLoginCommand,
    GoogleLoginUseCase,
    RequestPasswordResetCommand,
    RequestPasswordResetUseCase,
    ResetPasswordCommand,
    ResetPasswordUseCase,
    SendEmailVerificationCommand,
    SendEmailVerificationUseCase,
    UpdateProfileCommand,
    UpdateProfileUseCase,
)
from src.domain.auth.entities import EMAIL_VERIFICATION, PASSWORD_RESET, EmailToken, RefreshSession, User
from src.domain.auth.value_objects import AuthIdentity


class _UserRepo:
    def __init__(self) -> None:
        self.by_email: dict[str, User] = {}
        self.by_id: dict[str, User] = {}

    def create(self, user: User) -> User:
        self.by_email[user.email_normalized] = user
        self.by_id[user.id] = user
        return user

    def get_by_email(self, email_normalized: str) -> User | None:
        return self.by_email.get(email_normalized)

    def get_by_id(self, user_id: str) -> User | None:
        return self.by_id.get(user_id)

    def soft_delete(self, user_id: str, deleted_at: datetime) -> User | None:
        return None

    def hard_delete(self, user_id: str) -> bool:
        return False

    def _replace(self, user: User) -> User:
        self.by_id[user.id] = user
        self.by_email[user.email_normalized] = user
        return user

    def update_password_hash(self, user_id: str, password_hash: str, updated_at: datetime) -> User | None:
        user = self.by_id.get(user_id)
        if user is None or user.deleted_at is not None:
            return None
        return self._replace(User(**{**user.__dict__, "password_hash": password_hash, "updated_at": updated_at}))

    def update_profile(self, user_id: str, full_name: str | None, updated_at: datetime) -> User | None:
        user = self.by_id.get(user_id)
        if user is None or user.deleted_at is not None:
            return None
        return self._replace(User(**{**user.__dict__, "full_name": full_name, "updated_at": updated_at}))

    def mark_email_verified(self, user_id: str, updated_at: datetime) -> User | None:
        user = self.by_id.get(user_id)
        if user is None or user.deleted_at is not None:
            return None
        return self._replace(User(**{**user.__dict__, "email_verified": True, "updated_at": updated_at}))

    def set_auth_provider(self, user_id: str, auth_provider_id: str, updated_at: datetime) -> User | None:
        user = self.by_id.get(user_id)
        if user is None or user.deleted_at is not None:
            return None
        return self._replace(User(**{**user.__dict__, "auth_provider_id": auth_provider_id, "updated_at": updated_at}))


class _RefreshRepo:
    def __init__(self) -> None:
        self.sessions: list[RefreshSession] = []

    def create(self, session: RefreshSession) -> RefreshSession:
        self.sessions.append(session)
        return session

    def get_active_by_token_hash(self, token_hash: str, now: datetime) -> RefreshSession | None:
        return None

    def get_by_token_hash(self, token_hash: str) -> RefreshSession | None:
        return None

    def revoke(self, session_id: str, revoked_at: datetime) -> None:
        return None

    def rotate(self, *, old_session_id: str, new_session: RefreshSession, revoked_at: datetime) -> RefreshSession | None:
        return new_session

    def revoke_family(self, family_id: str, revoked_at: datetime) -> int:
        return 0

    def mark_reuse_detected(self, session_id: str, detected_at: datetime) -> None:
        return None

    def revoke_all_by_user_id(self, user_id: str, revoked_at: datetime) -> int:
        affected = 0
        for idx, session in enumerate(self.sessions):
            if session.user_id == user_id and session.revoked_at is None:
                self.sessions[idx] = RefreshSession(**{**session.__dict__, "revoked_at": revoked_at})
                affected += 1
        return affected


class _EmailTokens:
    def __init__(self) -> None:
        self.tokens: list[EmailToken] = []

    def create(self, token: EmailToken) -> EmailToken:
        self.tokens.append(token)
        return token

    def get_usable_by_hash(self, token_hash: str, purpose: str, now: datetime) -> EmailToken | None:
        for token in self.tokens:
            if token.token_hash == token_hash and token.purpose == purpose and token.is_usable(now):
                return token
        return None

    def mark_used(self, token_id: str, used_at: datetime) -> None:
        for idx, token in enumerate(self.tokens):
            if token.id == token_id:
                self.tokens[idx] = EmailToken(**{**token.__dict__, "used_at": used_at})
                return

    def delete(self, token_id: str) -> None:
        self.tokens = [token for token in self.tokens if token.id != token_id]

    def count_recent(self, user_id: str, purpose: str, since: datetime) -> int:
        return sum(1 for token in self.tokens if token.user_id == user_id and token.purpose == purpose and token.created_at >= since)


class _Hasher:
    def hash(self, plain_password: str) -> str:
        return f"hashed::{plain_password}"

    def verify(self, plain_password: str, password_hash: str) -> bool:
        return password_hash == self.hash(plain_password)


class _RefreshTokens:
    def __init__(self) -> None:
        self.counter = 0

    def generate_plain(self) -> str:
        self.counter += 1
        return f"plain-{self.counter}"

    def hash(self, token: str) -> str:
        return f"hash-{token}"

    def fingerprint(self, token: str) -> str:
        return token[:4]


class _Clock:
    def __init__(self) -> None:
        self.now_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.now_value


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def _next(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}-{self.value}"

    def new_id(self) -> str:
        return self._next("id")

    def new_jti(self) -> str:
        return self._next("jti")

    def new_family_id(self) -> str:
        return self._next("family")


class _Uow:
    @contextmanager
    def transaction(self):
        yield


class _Mail:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send(self, *, to: str, subject: str, html: str) -> None:
        self.sent.append({"to": to, "subject": subject, "html": html})


class _TokenIssuer:
    def issue_access(self, identity: AuthIdentity, jti: str, expires_at: datetime) -> str:
        return f"access::{identity.user_id}::{jti}"


class _GoogleVerifier:
    def __init__(self, identity: GoogleIdentity) -> None:
        self.identity = identity

    def verify(self, id_token: str) -> GoogleIdentity:
        if id_token != "good-token":
            raise AuthError(code=AUTH_TOKEN_INVALID, message="Google token is invalid")
        return self.identity


def _user(*, email: str = "user@example.com", password: str = "secret123") -> User:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return User(
        id="user-1",
        email_normalized=email,
        password_hash=f"hashed::{password}",
        email_verified=False,
        role="user",
        created_at=now,
        updated_at=now,
    )


class TestAccountRecoveryUseCases(unittest.TestCase):
    def test_forgot_password_is_silent_for_unknown_email(self) -> None:
        mail = _Mail()
        tokens = _EmailTokens()
        use_case = RequestPasswordResetUseCase(
            users=_UserRepo(),
            email_tokens=tokens,
            email_sender=mail,
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
            app_public_url="http://localhost:5173",
        )
        use_case.execute(RequestPasswordResetCommand(email="missing@example.com"))
        self.assertEqual(mail.sent, [])
        self.assertEqual(tokens.tokens, [])

    def test_forgot_password_emails_a_link_for_known_user(self) -> None:
        users = _UserRepo()
        users.create(_user())
        mail = _Mail()
        tokens = _EmailTokens()
        use_case = RequestPasswordResetUseCase(
            users=users,
            email_tokens=tokens,
            email_sender=mail,
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
            app_public_url="http://localhost:5173",
        )
        use_case.execute(RequestPasswordResetCommand(email="User@Example.com"))
        self.assertEqual(len(tokens.tokens), 1)
        self.assertEqual(tokens.tokens[0].purpose, PASSWORD_RESET)
        self.assertEqual(len(mail.sent), 1)
        self.assertIn("restablecer-password?token=plain-1", mail.sent[0]["html"])

    def test_forgot_password_drops_token_when_mail_fails(self) -> None:
        class _FailingMail:
            def send(self, *, to: str, subject: str, html: str) -> None:
                raise AuthError(code="AUTH_INTERNAL", message="Failed to send email")

        users = _UserRepo()
        users.create(_user())
        tokens = _EmailTokens()
        use_case = RequestPasswordResetUseCase(
            users=users,
            email_tokens=tokens,
            email_sender=_FailingMail(),
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
            app_public_url="http://localhost:5173",
        )
        use_case.execute(RequestPasswordResetCommand(email="user@example.com"))
        self.assertEqual(tokens.tokens, [])

    def test_reset_password_updates_hash_and_revokes_sessions(self) -> None:
        users = _UserRepo()
        users.create(_user())
        refresh = _RefreshRepo()
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        refresh.create(
            RefreshSession(
                id="s1",
                user_id="user-1",
                token_hash="x",
                token_jti="j",
                family_id="f",
                issued_at=now,
                expires_at=now + timedelta(days=7),
            )
        )
        tokens = _EmailTokens()
        tokens.create(
            EmailToken(
                id="tok-1",
                user_id="user-1",
                purpose=PASSWORD_RESET,
                token_hash="hash-reset-token",
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        use_case = ResetPasswordUseCase(
            users=users,
            email_tokens=tokens,
            refresh_sessions=refresh,
            password_hasher=_Hasher(),
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            uow=_Uow(),
        )
        use_case.execute(ResetPasswordCommand(token="reset-token", password="newsecret1"))
        self.assertEqual(users.get_by_id("user-1").password_hash, "hashed::newsecret1")
        self.assertIsNotNone(tokens.tokens[0].used_at)
        self.assertIsNotNone(refresh.sessions[0].revoked_at)

    def test_reset_password_rejects_unknown_token(self) -> None:
        use_case = ResetPasswordUseCase(
            users=_UserRepo(),
            email_tokens=_EmailTokens(),
            refresh_sessions=_RefreshRepo(),
            password_hasher=_Hasher(),
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            uow=_Uow(),
        )
        with self.assertRaises(AuthError) as raised:
            use_case.execute(ResetPasswordCommand(token="nope", password="newsecret1"))
        self.assertEqual(raised.exception.code, AUTH_TOKEN_INVALID)

    def test_change_password_requires_current_password(self) -> None:
        users = _UserRepo()
        users.create(_user())
        use_case = ChangePasswordUseCase(
            users=users,
            refresh_sessions=_RefreshRepo(),
            password_hasher=_Hasher(),
            clock=_Clock(),
            uow=_Uow(),
        )
        with self.assertRaises(AuthError) as raised:
            use_case.execute(
                ChangePasswordCommand(user_id="user-1", current_password="wrong", new_password="newsecret1")
            )
        self.assertEqual(raised.exception.code, AUTH_INVALID_CREDENTIALS)

    def test_update_profile_persists_name(self) -> None:
        users = _UserRepo()
        users.create(_user())
        identity = UpdateProfileUseCase(users=users, clock=_Clock(), uow=_Uow()).execute(
            UpdateProfileCommand(user_id="user-1", full_name="  Jayson Tatum  ")
        )
        self.assertEqual(identity.full_name, "Jayson Tatum")

    def test_email_verification_round_trip(self) -> None:
        users = _UserRepo()
        users.create(_user())
        tokens = _EmailTokens()
        mail = _Mail()
        SendEmailVerificationUseCase(
            users=users,
            email_tokens=tokens,
            email_sender=mail,
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
            app_public_url="http://localhost:5173",
        ).execute(SendEmailVerificationCommand(user_id="user-1"))
        self.assertEqual(tokens.tokens[0].purpose, EMAIL_VERIFICATION)
        identity = ConfirmEmailVerificationUseCase(
            users=users,
            email_tokens=tokens,
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            uow=_Uow(),
        ).execute(ConfirmEmailVerificationCommand(token="plain-1"))
        self.assertTrue(identity.email_verified)

    def test_google_login_creates_verified_user(self) -> None:
        users = _UserRepo()
        result = GoogleLoginUseCase(
            users=users,
            refresh_sessions=_RefreshRepo(),
            password_hasher=_Hasher(),
            token_issuer=_TokenIssuer(),
            refresh_tokens=_RefreshTokens(),
            verifier=_GoogleVerifier(
                GoogleIdentity(subject="sub-1", email="jay@example.com", email_verified=True, full_name="Jay")
            ),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
        ).execute(GoogleLoginCommand(id_token="good-token"))
        self.assertEqual(result.user.email, "jay@example.com")
        self.assertTrue(result.user.email_verified)
        self.assertEqual(result.user.full_name, "Jay")
        self.assertTrue(result.tokens.access_token.startswith("access::"))

    def test_google_login_links_existing_account(self) -> None:
        users = _UserRepo()
        users.create(_user(email="jay@example.com"))
        result = GoogleLoginUseCase(
            users=users,
            refresh_sessions=_RefreshRepo(),
            password_hasher=_Hasher(),
            token_issuer=_TokenIssuer(),
            refresh_tokens=_RefreshTokens(),
            verifier=_GoogleVerifier(
                GoogleIdentity(subject="sub-1", email="jay@example.com", email_verified=True, full_name="Jay")
            ),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
        ).execute(GoogleLoginCommand(id_token="good-token"))
        self.assertEqual(result.user.user_id, "user-1")
        self.assertEqual(users.get_by_id("user-1").auth_provider_id, "google:sub-1")
        self.assertTrue(users.get_by_id("user-1").email_verified)


if __name__ == "__main__":
    unittest.main()
