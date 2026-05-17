from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class User:
    id: str
    email_normalized: str
    password_hash: str
    email_verified: bool = False
    role: str = "user"
    auth_provider_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class RefreshSession:
    id: str
    user_id: str
    token_hash: str
    token_jti: str
    family_id: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    replaced_by_session_id: str | None = None
    reuse_detected_at: datetime | None = None
    user_agent: str | None = None
    ip: str | None = None

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at

    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_active(self, now: datetime) -> bool:
        return not self.is_revoked() and not self.is_expired(now)
