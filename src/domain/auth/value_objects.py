from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Email:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not normalized or "@" not in normalized:
            raise ValueError("Invalid email format")
        local, _, domain = normalized.partition("@")
        if not local or not domain or "." not in domain:
            raise ValueError("Invalid email format")
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True)
class PlainPassword:
    value: str
    min_length: int = 8

    def __post_init__(self) -> None:
        if len(self.value) < self.min_length:
            raise ValueError("Password too short")


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


@dataclass(frozen=True)
class AuthIdentity:
    user_id: str
    email: str
    role: str
    email_verified: bool
