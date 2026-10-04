from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from src.application.common.ports import IdGeneratorPort, UnitOfWorkPort
from src.domain.auth.entities import EmailToken, RefreshSession, User
from src.domain.auth.value_objects import AuthIdentity


class UserRepositoryPort(ABC):
    """Persistence contract for auth users.

    Application semantics:
    - ``get_by_*`` may return soft-deleted users; use cases enforce auth policy.
    - ``soft_delete`` is idempotent and returns the mutated entity only once.
    """

    @abstractmethod
    def create(self, user: User) -> User:
        raise NotImplementedError

    @abstractmethod
    def get_by_email(self, email_normalized: str) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, user_id: str) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def soft_delete(self, user_id: str, deleted_at: datetime) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def hard_delete(self, user_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def update_password_hash(self, user_id: str, password_hash: str, updated_at: datetime) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def update_profile(self, user_id: str, full_name: str | None, updated_at: datetime) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def mark_email_verified(self, user_id: str, updated_at: datetime) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def set_auth_provider(self, user_id: str, auth_provider_id: str, updated_at: datetime) -> User | None:
        raise NotImplementedError


class RefreshSessionRepositoryPort(ABC):
    """Persistence contract for refresh-token lifecycle operations.

    Security invariants consumed by use cases:
    - ``get_active_by_token_hash`` returns only non-revoked, non-expired sessions.
    - ``rotate`` returns ``None`` when old session is not rotatable anymore.
    - revoke methods are idempotent and safe for repeated calls.
    """

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
    ) -> RefreshSession | None:
        raise NotImplementedError

    @abstractmethod
    def revoke_family(self, family_id: str, revoked_at: datetime) -> int:
        raise NotImplementedError

    @abstractmethod
    def mark_reuse_detected(self, session_id: str, detected_at: datetime) -> None:
        raise NotImplementedError

    @abstractmethod
    def revoke_all_by_user_id(self, user_id: str, revoked_at: datetime) -> int:
        raise NotImplementedError


class PasswordHasherPort(ABC):
    """Password hashing boundary for credential verification flows."""

    @abstractmethod
    def hash(self, plain_password: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def verify(self, plain_password: str, password_hash: str) -> bool:
        raise NotImplementedError


class TokenIssuerPort(ABC):
    """Access-token issuing boundary (JWT or equivalent)."""

    @abstractmethod
    def issue_access(self, identity: AuthIdentity, jti: str, expires_at: datetime) -> str:
        raise NotImplementedError


class RefreshTokenServicePort(ABC):
    """Opaque refresh-token generation/hash boundary.

    Storage invariant: plain tokens never persist; only ``hash`` outputs are stored.
    """

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
    """Time provider boundary used for deterministic expiration semantics."""

    @abstractmethod
    def now(self) -> datetime:
        raise NotImplementedError


class AuthIdGeneratorPort(IdGeneratorPort, ABC):
    """ID factory for auth entity ids plus token-family identifiers."""

    @abstractmethod
    def new_jti(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def new_family_id(self) -> str:
        raise NotImplementedError


class EmailTokenRepositoryPort(ABC):
    """Persistence contract for one-time tokens delivered by email."""

    @abstractmethod
    def create(self, token: EmailToken) -> EmailToken:
        raise NotImplementedError

    @abstractmethod
    def get_usable_by_hash(self, token_hash: str, purpose: str, now: datetime) -> EmailToken | None:
        raise NotImplementedError

    @abstractmethod
    def mark_used(self, token_id: str, used_at: datetime) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, token_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def count_recent(self, user_id: str, purpose: str, since: datetime) -> int:
        raise NotImplementedError


class EmailSenderPort(ABC):
    """Outbound email boundary. Implementations must not log the recipient body."""

    @abstractmethod
    def send(self, *, to: str, subject: str, html: str) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class GoogleIdentity:
    """Verified claims extracted from a Google ID token."""

    subject: str
    email: str
    email_verified: bool
    full_name: str | None = None


class GoogleIdTokenVerifierPort(ABC):
    """Validates a Google ID token and returns its identity claims."""

    @abstractmethod
    def verify(self, id_token: str) -> GoogleIdentity:
        raise NotImplementedError
