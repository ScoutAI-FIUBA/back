from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from datetime import datetime

from src.domain.auth.entities import RefreshSession, User
from src.domain.auth.value_objects import AuthIdentity


class UserRepositoryPort(ABC):
    @abstractmethod
    def create(self, user: User) -> User:
        raise NotImplementedError

    @abstractmethod
    def get_by_email(self, email_normalized: str) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, user_id: str) -> User | None:
        raise NotImplementedError


class RefreshSessionRepositoryPort(ABC):
    @abstractmethod
    def create(self, session: RefreshSession) -> RefreshSession:
        raise NotImplementedError

    @abstractmethod
    def get_active_by_token_hash(self, token_hash: str, now: datetime) -> RefreshSession | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_token_hash(self, token_hash: str) -> RefreshSession | None:
        raise NotImplementedError

    @abstractmethod
    def revoke(self, session_id: str, revoked_at: datetime) -> None:
        raise NotImplementedError

    @abstractmethod
    def rotate(
        self,
        *,
        old_session_id: str,
        new_session: RefreshSession,
        revoked_at: datetime,
    ) -> RefreshSession:
        raise NotImplementedError

    @abstractmethod
    def revoke_family(self, family_id: str, revoked_at: datetime) -> int:
        raise NotImplementedError

    @abstractmethod
    def mark_reuse_detected(self, session_id: str, detected_at: datetime) -> None:
        raise NotImplementedError


class PasswordHasherPort(ABC):
    @abstractmethod
    def hash(self, plain_password: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def verify(self, plain_password: str, password_hash: str) -> bool:
        raise NotImplementedError


class TokenIssuerPort(ABC):
    @abstractmethod
    def issue_access(self, identity: AuthIdentity, jti: str, expires_at: datetime) -> str:
        raise NotImplementedError


class RefreshTokenServicePort(ABC):
    @abstractmethod
    def generate_plain(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def hash(self, token: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def fingerprint(self, token: str) -> str:
        raise NotImplementedError


class ClockPort(ABC):
    @abstractmethod
    def now(self) -> datetime:
        raise NotImplementedError


class IdGeneratorPort(ABC):
    @abstractmethod
    def new_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def new_jti(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def new_family_id(self) -> str:
        raise NotImplementedError


class UnitOfWorkPort(ABC):
    @abstractmethod
    def transaction(self) -> AbstractContextManager[None]:
        raise NotImplementedError
