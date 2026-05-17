from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import unittest

from src.application.auth.errors import AUTH_EMAIL_ALREADY_EXISTS, AUTH_INVALID_CREDENTIALS, AuthError
from src.application.auth.use_cases import LoginCommand, LoginUseCase, RegisterUserCommand, RegisterUserUseCase
from src.domain.auth.entities import RefreshSession, User
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
        user = self.by_id.get(user_id)
        if user is None or user.deleted_at is not None:
            return None
        deleted = User(**{**user.__dict__, "deleted_at": deleted_at, "updated_at": deleted_at})
        self.by_id[user_id] = deleted
        self.by_email[deleted.email_normalized] = deleted
        return deleted

    def hard_delete(self, user_id: str) -> bool:
        user = self.by_id.pop(user_id, None)
        if user is None:
            return False
        self.by_email.pop(user.email_normalized, None)
        return True


class _RefreshRepo:
    def __init__(self) -> None:
        self.sessions: list[RefreshSession] = []

    def create(self, session: RefreshSession) -> RefreshSession:
        self.sessions.append(session)
        return session

    def get_active_by_token_hash(self, token_hash: str, now: datetime) -> RefreshSession | None:
        for session in self.sessions:
            if session.token_hash == token_hash and session.is_active(now):
                return session
        return None

    def get_by_token_hash(self, token_hash: str) -> RefreshSession | None:
        for session in self.sessions:
            if session.token_hash == token_hash:
                return session
        return None

    def revoke(self, session_id: str, revoked_at: datetime) -> None:
        for idx, session in enumerate(self.sessions):
            if session.id == session_id:
                self.sessions[idx] = RefreshSession(**{**session.__dict__, "revoked_at": revoked_at})
                return

    def rotate(self, *, old_session_id: str, new_session: RefreshSession, revoked_at: datetime) -> RefreshSession:
        self.revoke(old_session_id, revoked_at)
        self.sessions.append(new_session)
        return new_session

    def revoke_family(self, family_id: str, revoked_at: datetime) -> int:
        affected = 0
        for idx, session in enumerate(self.sessions):
            if session.family_id == family_id and session.revoked_at is None:
                self.sessions[idx] = RefreshSession(**{**session.__dict__, "revoked_at": revoked_at})
                affected += 1
        return affected

    def mark_reuse_detected(self, session_id: str, detected_at: datetime) -> None:
        for idx, session in enumerate(self.sessions):
            if session.id == session_id:
                self.sessions[idx] = RefreshSession(**{**session.__dict__, "reuse_detected_at": detected_at})
                return

    def revoke_all_by_user_id(self, user_id: str, revoked_at: datetime) -> int:
        affected = 0
        for idx, session in enumerate(self.sessions):
            if session.user_id == user_id and session.revoked_at is None:
                self.sessions[idx] = RefreshSession(**{**session.__dict__, "revoked_at": revoked_at})
                affected += 1
        return affected


class _Hasher:
    def hash(self, plain_password: str) -> str:
        return f"hashed::{plain_password}"

    def verify(self, plain_password: str, password_hash: str) -> bool:
        return password_hash == self.hash(plain_password)


class _TokenIssuer:
    def issue_access(self, identity: AuthIdentity, jti: str, expires_at: datetime) -> str:
        return f"token::{identity.user_id}::{jti}::{int(expires_at.timestamp())}"


class _RefreshTokens:
    def generate_plain(self) -> str:
        return "refresh-plain"

    def hash(self, token: str) -> str:
        return f"refresh-hash::{token}"

    def fingerprint(self, token: str) -> str:
        return "fp"


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Ids:
    def __init__(self) -> None:
        self.n = 0

    def _next(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}-{self.n}"

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


class TestRegisterLoginUseCases(unittest.TestCase):
    def test_register_success_and_no_plaintext_storage(self) -> None:
        users = _UserRepo()
        use_case = RegisterUserUseCase(users=users, password_hasher=_Hasher(), clock=_Clock(), ids=_Ids())

        identity = use_case.execute(RegisterUserCommand(email="  USER@example.com ", password="supersecret"))

        self.assertEqual(identity.email, "user@example.com")
        self.assertEqual(identity.role, "user")
        self.assertFalse(identity.email_verified)
        stored = users.get_by_email("user@example.com")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertNotEqual(stored.password_hash, "supersecret")
        self.assertTrue(stored.password_hash.startswith("hashed::"))

    def test_register_duplicate_email(self) -> None:
        users = _UserRepo()
        existing = User(id="u1", email_normalized="user@example.com", password_hash="h")
        users.create(existing)
        use_case = RegisterUserUseCase(users=users, password_hasher=_Hasher(), clock=_Clock(), ids=_Ids())

        with self.assertRaises(AuthError) as ctx:
            use_case.execute(RegisterUserCommand(email="USER@example.com", password="supersecret"))
        self.assertEqual(ctx.exception.code, AUTH_EMAIL_ALREADY_EXISTS)

    def test_login_invalid_credentials(self) -> None:
        users = _UserRepo()
        users.create(User(id="u1", email_normalized="user@example.com", password_hash="hashed::right-pass"))
        use_case = LoginUseCase(
            users=users,
            refresh_sessions=_RefreshRepo(),
            password_hasher=_Hasher(),
            token_issuer=_TokenIssuer(),
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
        )

        with self.assertRaises(AuthError) as ctx:
            use_case.execute(LoginCommand(email="user@example.com", password="wrong-pass"))
        self.assertEqual(ctx.exception.code, AUTH_INVALID_CREDENTIALS)

    def test_login_success_issues_tokens_and_persists_session(self) -> None:
        users = _UserRepo()
        users.create(User(id="u1", email_normalized="user@example.com", password_hash="hashed::right-pass"))
        refresh_repo = _RefreshRepo()
        use_case = LoginUseCase(
            users=users,
            refresh_sessions=refresh_repo,
            password_hasher=_Hasher(),
            token_issuer=_TokenIssuer(),
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
        )

        result = use_case.execute(LoginCommand(email="USER@example.com", password="right-pass"))

        self.assertEqual(result.tokens.token_type, "Bearer")
        self.assertEqual(result.tokens.expires_in, 900)
        self.assertEqual(result.tokens.refresh_token, "refresh-plain")
        self.assertEqual(result.user.user_id, "u1")
        self.assertEqual(len(refresh_repo.sessions), 1)
        self.assertEqual(refresh_repo.sessions[0].token_hash, "refresh-hash::refresh-plain")

    def test_login_rejects_soft_deleted_user(self) -> None:
        users = _UserRepo()
        users.create(
            User(
                id="u1",
                email_normalized="user@example.com",
                password_hash="hashed::right-pass",
                deleted_at=datetime(2025, 12, 31, tzinfo=timezone.utc),
            )
        )
        use_case = LoginUseCase(
            users=users,
            refresh_sessions=_RefreshRepo(),
            password_hasher=_Hasher(),
            token_issuer=_TokenIssuer(),
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
        )

        with self.assertRaises(AuthError) as ctx:
            use_case.execute(LoginCommand(email="user@example.com", password="right-pass"))
        self.assertEqual(ctx.exception.code, AUTH_INVALID_CREDENTIALS)


if __name__ == "__main__":
    unittest.main()
