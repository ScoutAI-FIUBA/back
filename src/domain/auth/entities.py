"""Core authentication entities.

These dataclasses are immutable domain records that capture user identity and
refresh-token session lifecycle state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class User:
    """Represents an authentication user account.

    Invariants expected by callers:
    - `email_normalized` is already canonicalized for identity comparison.
    - `password_hash` is never a plain password.
    - `deleted_at` being set marks a soft-deleted account.
    """

    id: str
    email_normalized: str
    password_hash: str
    email_verified: bool = False
    role: str = "user"
    auth_provider_id: str | None = None
    full_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


PASSWORD_RESET = "password_reset"
EMAIL_VERIFICATION = "email_verification"


@dataclass(frozen=True)
class EmailToken:
    """Represents a single-use token sent to a user's inbox.

    Invariants expected by callers:
    - `token_hash` is a digest; the plain token exists only inside the email.
    - `purpose` is one of `PASSWORD_RESET` or `EMAIL_VERIFICATION`.
    - consuming the token records `used_at`, which makes it unusable again.
    """

    id: str
    user_id: str
    purpose: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None

    def is_expired(self, now: datetime) -> bool:
        """Return whether the token can no longer be redeemed by time."""
        return now >= self.expires_at

    def is_used(self) -> bool:
        """Return whether the token was already redeemed."""
        return self.used_at is not None

    def is_usable(self, now: datetime) -> bool:
        """Return whether the token may still be redeemed."""
        return not self.is_used() and not self.is_expired(now)


@dataclass(frozen=True)
class RefreshSession:
    """Represents a refresh-token session and rotation lineage.

    Identity/lifecycle semantics:
    - `token_jti` uniquely identifies the concrete issued refresh token.
    - `family_id` groups rotated sessions from the same login chain.
    - `replaced_by_session_id` links to the next rotated session.
    """

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
        """Return whether the session can no longer be used by time."""
        return now >= self.expires_at

    def is_revoked(self) -> bool:
        """Return whether explicit revocation has been recorded."""
        return self.revoked_at is not None

    def is_active(self, now: datetime) -> bool:
        """Return whether the session is currently valid for refresh usage."""
        return not self.is_revoked() and not self.is_expired(now)
