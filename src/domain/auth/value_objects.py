"""Authentication domain value objects.

These objects enforce normalization and validation close to construction to keep
authentication invariants explicit and immutable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Email:
    """Normalized email value object.

    Normalization semantics:
    - Trims surrounding whitespace.
    - Lowercases the whole address for case-insensitive identity matching.

    Validation rules are intentionally minimal and structural (presence of local
    part, domain part, and dot in domain).
    """

    value: str

    def __post_init__(self) -> None:
        """Validate and persist the normalized representation."""
        normalized = self.value.strip().lower()
        if not normalized or "@" not in normalized:
            raise ValueError("Invalid email format")
        local, _, domain = normalized.partition("@")
        if not local or not domain or "." not in domain:
            raise ValueError("Invalid email format")
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True)
class PlainPassword:
    """Raw password value object used before hashing.

    This type only enforces minimum length; complexity requirements (if any)
    should be enforced at policy/service level.
    """

    value: str
    min_length: int = 8

    def __post_init__(self) -> None:
        """Reject passwords shorter than the configured minimum length."""
        if len(self.value) < self.min_length:
            raise ValueError("Password too short")


@dataclass(frozen=True)
class TokenPair:
    """Issued access/refresh token pair returned by auth services.

    `expires_in` expresses access token lifetime in seconds.
    """

    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


@dataclass(frozen=True)
class AuthIdentity:
    """Authenticated principal snapshot used by application boundaries.

    `email` should already be normalized by the producer.
    """

    user_id: str
    email: str
    role: str
    email_verified: bool
    full_name: str | None = None
