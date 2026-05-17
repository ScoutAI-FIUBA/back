from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import unittest

from fastapi import Response

from src.application.auth.use_cases import (
    GetCurrentUserUseCase,
    LoginUseCase,
    LogoutUseCase,
    RefreshSessionUseCase,
    RegisterUserUseCase,
)
from src.domain.auth.entities import RefreshSession, User
from src.interfaces.http.auth_router import create_auth_router


class _UserRepo:
    def __init__(self) -> None:
        self.by_email = {}
        self.by_id = {}

    def create(self, user):
        self.by_email[user.email_normalized] = user
        self.by_id[user.id] = user
        return user

    def get_by_email(self, email_normalized: str):
        return self.by_email.get(email_normalized)

    def get_by_id(self, user_id: str):
        return self.by_id.get(user_id)


class _RefreshRepo:
    def __init__(self) -> None:
        self.sessions = []

    def create(self, session):
        self.sessions.append(session)
        return session

    def get_active_by_token_hash(self, token_hash: str, now: datetime):
        for session in self.sessions:
            if session.token_hash == token_hash and session.is_active(now):
                return session
        return None

    def get_by_token_hash(self, token_hash: str):
        for session in self.sessions:
            if session.token_hash == token_hash:
                return session
        return None

    def revoke(self, session_id: str, revoked_at: datetime):
        for idx, session in enumerate(self.sessions):
            if session.id == session_id:
                self.sessions[idx] = RefreshSession(**{**session.__dict__, "revoked_at": revoked_at})
                return

    def rotate(self, *, old_session_id: str, new_session: RefreshSession, revoked_at: datetime):
        self.revoke(old_session_id, revoked_at)
        self.sessions.append(new_session)
        return new_session

    def revoke_family(self, family_id: str, revoked_at: datetime):
        affected = 0
        for idx, session in enumerate(self.sessions):
            if session.family_id == family_id and session.revoked_at is None:
                self.sessions[idx] = RefreshSession(**{**session.__dict__, "revoked_at": revoked_at})
                affected += 1
        return affected

    def mark_reuse_detected(self, session_id: str, detected_at: datetime):
        for idx, session in enumerate(self.sessions):
            if session.id == session_id:
                self.sessions[idx] = RefreshSession(**{**session.__dict__, "reuse_detected_at": detected_at})
                return


class _Hasher:
    def hash(self, plain_password: str) -> str:
        return f"hashed::{plain_password}"

    def verify(self, plain_password: str, password_hash: str) -> bool:
        return password_hash == self.hash(plain_password)


class _TokenIssuer:
    def issue_access(self, identity, jti: str, expires_at: datetime) -> str:
        return f"token-{identity.user_id}-{jti}"


class _RefreshTokens:
    def generate_plain(self) -> str:
        return "refresh-token"

    def hash(self, token: str) -> str:
        return f"hash-{token}"

    def fingerprint(self, token: str) -> str:
        return "fp"


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=timezone.utc)


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


class TestAuthRegisterLoginHTTP(unittest.TestCase):
    def _endpoints(self):
        users = _UserRepo()
        refresh_repo = _RefreshRepo()
        register = RegisterUserUseCase(users=users, password_hasher=_Hasher(), clock=_Clock(), ids=_Ids())
        login = LoginUseCase(
            users=users,
            refresh_sessions=refresh_repo,
            password_hasher=_Hasher(),
            token_issuer=_TokenIssuer(),
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
        )
        refresh = RefreshSessionUseCase(
            users=users,
            refresh_sessions=refresh_repo,
            token_issuer=_TokenIssuer(),
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            ids=_Ids(),
            uow=_Uow(),
        )
        logout = LogoutUseCase(
            refresh_sessions=refresh_repo,
            refresh_tokens=_RefreshTokens(),
            clock=_Clock(),
            uow=_Uow(),
        )
        me = GetCurrentUserUseCase(users=users)
        router = create_auth_router(
            register_use_case=register,
            login_use_case=login,
            refresh_use_case=refresh,
            logout_use_case=logout,
            current_user_use_case=me,
            access_token_resolver=lambda _: "id-1",
        )
        register_endpoint = next(route.endpoint for route in router.routes if route.path.endswith("/register"))
        login_endpoint = next(route.endpoint for route in router.routes if route.path.endswith("/login"))
        return register_endpoint, login_endpoint

    def test_register_and_login_cookie_contract(self) -> None:
        register_endpoint, login_endpoint = self._endpoints()
        register = register_endpoint(type("RegisterRequest", (), {"email": "user@example.com", "password": "supersecret"})())
        self.assertNotIn("password_hash", register["user"])

        response = Response()
        payload = login_endpoint(
            type("LoginRequest", (), {"email": "user@example.com", "password": "supersecret"})(),
            response,
        )
        self.assertIn("access_token", payload)
        self.assertNotIn("refresh_token", payload)
        cookie_header = response.headers.get("set-cookie", "").lower()
        self.assertIn("httponly", cookie_header)
        self.assertIn("secure", cookie_header)
        self.assertIn("samesite=strict", cookie_header)


if __name__ == "__main__":
    unittest.main()
