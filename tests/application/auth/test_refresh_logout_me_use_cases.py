from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import unittest

from src.application.auth.errors import AUTH_REFRESH_REUSED, AUTH_TOKEN_INVALID, AUTH_UNAUTHORIZED, AuthError
from src.application.auth.use_cases import (
    DeleteCurrentUserCommand,
    DeleteCurrentUserUseCase,
    GetCurrentUserQuery,
    GetCurrentUserUseCase,
    HardDeleteUserCommand,
    HardDeleteUserUseCase,
    LogoutCommand,
    LogoutUseCase,
    RefreshSessionCommand,
    RefreshSessionUseCase,
)
from src.domain.auth.entities import RefreshSession, User
from src.domain.auth.value_objects import AuthIdentity


class _UserRepo:
    def __init__(self) -> None:
        self.by_id: dict[str, User] = {}

    def create(self, user: User) -> User:
        self.by_id[user.id] = user
        return user

    def get_by_email(self, email_normalized: str) -> User | None:
        return None

    def get_by_id(self, user_id: str) -> User | None:
        return self.by_id.get(user_id)

    def soft_delete(self, user_id: str, deleted_at: datetime) -> User | None:
        user = self.by_id.get(user_id)
        if user is None or user.deleted_at is not None:
            return None
        deleted = User(**{**user.__dict__, "deleted_at": deleted_at, "updated_at": deleted_at})
        self.by_id[user_id] = deleted
        return deleted

    def hard_delete(self, user_id: str) -> bool:
        return self.by_id.pop(user_id, None) is not None


class _RefreshRepo:
    def __init__(self) -> None:
        self.sessions: list[RefreshSession] = []
        self.fail_rotate = False

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

    def rotate(
        self,
        *,
        old_session_id: str,
        new_session: RefreshSession,
        revoked_at: datetime,
    ) -> RefreshSession | None:
        if self.fail_rotate:
            return None
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


class _TokenIssuer:
    def issue_access(self, identity: AuthIdentity, jti: str, expires_at: datetime) -> str:
        return f"token::{identity.user_id}::{jti}::{int(expires_at.timestamp())}"


class _RefreshTokens:
    def generate_plain(self) -> str:
        return "new-refresh"

    def hash(self, token: str) -> str:
        return f"hash::{token}"

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


class TestRefreshLogoutMeUseCases(unittest.TestCase):
    def test_refresh_success_rotates_token(self) -> None:
        users = _UserRepo()
        users.create(User(id="u1", email_normalized="u@example.com", password_hash="h"))
        refresh_repo = _RefreshRepo()
        refresh_repo.create(
            RefreshSession(
                id="s1",
                user_id="u1",
                token_hash="hash::old-refresh",
                token_jti="jti-old",
                family_id="fam-1",
                issued_at=_Clock().now(),
                expires_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
        )
        use_case = RefreshSessionUseCase(
            users=users,
            refresh_sessions=refresh_repo,
            token_issuer=_TokenIssuer(),
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
        )

        result = use_case.execute(RefreshSessionCommand(refresh_token="old-refresh"))

        self.assertEqual(result.tokens.refresh_token, "new-refresh")
        self.assertEqual(len(refresh_repo.sessions), 2)
        old = refresh_repo.get_by_token_hash("hash::old-refresh")
        self.assertIsNotNone(old)
        assert old is not None
        self.assertIsNotNone(old.revoked_at)

    def test_refresh_reuse_detected_revokes_family(self) -> None:
        users = _UserRepo()
        users.create(User(id="u1", email_normalized="u@example.com", password_hash="h"))
        refresh_repo = _RefreshRepo()
        refresh_repo.create(
            RefreshSession(
                id="s1",
                user_id="u1",
                token_hash="hash::old-refresh",
                token_jti="jti-old",
                family_id="fam-1",
                issued_at=datetime(2025, 12, 20, tzinfo=timezone.utc),
                expires_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                revoked_at=datetime(2025, 12, 21, tzinfo=timezone.utc),
            )
        )
        refresh_repo.create(
            RefreshSession(
                id="s2",
                user_id="u1",
                token_hash="hash::other",
                token_jti="jti-next",
                family_id="fam-1",
                issued_at=datetime(2025, 12, 21, tzinfo=timezone.utc),
                expires_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
            )
        )
        use_case = RefreshSessionUseCase(
            users=users,
            refresh_sessions=refresh_repo,
            token_issuer=_TokenIssuer(),
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
        )

        with self.assertRaises(AuthError) as ctx:
            use_case.execute(RefreshSessionCommand(refresh_token="old-refresh"))
        self.assertEqual(ctx.exception.code, AUTH_REFRESH_REUSED)
        reused = refresh_repo.get_by_token_hash("hash::old-refresh")
        self.assertIsNotNone(reused)
        assert reused is not None
        self.assertIsNotNone(reused.reuse_detected_at)
        sibling = refresh_repo.get_by_token_hash("hash::other")
        self.assertIsNotNone(sibling)
        assert sibling is not None
        self.assertIsNotNone(sibling.revoked_at)

    def test_refresh_concurrent_rotation_returns_reuse_error(self) -> None:
        users = _UserRepo()
        users.create(User(id="u1", email_normalized="u@example.com", password_hash="h"))
        refresh_repo = _RefreshRepo()
        refresh_repo.fail_rotate = True
        refresh_repo.create(
            RefreshSession(
                id="s1",
                user_id="u1",
                token_hash="hash::old-refresh",
                token_jti="jti-old",
                family_id="fam-1",
                issued_at=_Clock().now(),
                expires_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
        )
        use_case = RefreshSessionUseCase(
            users=users,
            refresh_sessions=refresh_repo,
            token_issuer=_TokenIssuer(),
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
        )

        with self.assertRaises(AuthError) as ctx:
            use_case.execute(RefreshSessionCommand(refresh_token="old-refresh"))
        self.assertEqual(ctx.exception.code, AUTH_REFRESH_REUSED)
        self.assertEqual(len(refresh_repo.sessions), 1)

    def test_logout_idempotent(self) -> None:
        refresh_repo = _RefreshRepo()
        use_case = LogoutUseCase(
            refresh_sessions=refresh_repo,
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            uow=_Uow(),
        )

        use_case.execute(LogoutCommand(refresh_token="absent"))

    def test_me_user_missing_unauthorized(self) -> None:
        use_case = GetCurrentUserUseCase(users=_UserRepo())
        with self.assertRaises(AuthError) as ctx:
            use_case.execute(GetCurrentUserQuery(user_id="missing"))
        self.assertEqual(ctx.exception.code, AUTH_UNAUTHORIZED)

    def test_me_soft_deleted_user_unauthorized(self) -> None:
        users = _UserRepo()
        users.create(
            User(
                id="u1",
                email_normalized="u@example.com",
                password_hash="h",
                deleted_at=datetime(2025, 12, 31, tzinfo=timezone.utc),
            )
        )
        use_case = GetCurrentUserUseCase(users=users)
        with self.assertRaises(AuthError) as ctx:
            use_case.execute(GetCurrentUserQuery(user_id="u1"))
        self.assertEqual(ctx.exception.code, AUTH_UNAUTHORIZED)

    def test_delete_current_user_soft_deletes_and_revokes_sessions(self) -> None:
        users = _UserRepo()
        users.create(User(id="u1", email_normalized="u@example.com", password_hash="h"))
        refresh_repo = _RefreshRepo()
        refresh_repo.create(
            RefreshSession(
                id="s1",
                user_id="u1",
                token_hash="hash::a",
                token_jti="j1",
                family_id="f1",
                issued_at=datetime(2025, 12, 20, tzinfo=timezone.utc),
                expires_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
        )
        use_case = DeleteCurrentUserUseCase(users=users, refresh_sessions=refresh_repo, clock=_Clock(), uow=_Uow())

        use_case.execute(DeleteCurrentUserCommand(user_id="u1"))

        self.assertIsNotNone(users.get_by_id("u1").deleted_at)
        self.assertIsNotNone(refresh_repo.sessions[0].revoked_at)

    def test_hard_delete_user_purges_user_and_revokes_sessions(self) -> None:
        users = _UserRepo()
        users.create(User(id="u1", email_normalized="u@example.com", password_hash="h"))
        refresh_repo = _RefreshRepo()
        refresh_repo.create(
            RefreshSession(
                id="s1",
                user_id="u1",
                token_hash="hash::a",
                token_jti="j1",
                family_id="f1",
                issued_at=datetime(2025, 12, 20, tzinfo=timezone.utc),
                expires_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
        )
        use_case = HardDeleteUserUseCase(users=users, refresh_sessions=refresh_repo, clock=_Clock(), uow=_Uow())

        use_case.execute(HardDeleteUserCommand(user_id="u1"))

        self.assertIsNone(users.get_by_id("u1"))
        self.assertIsNotNone(refresh_repo.sessions[0].revoked_at)


if __name__ == "__main__":
    unittest.main()
