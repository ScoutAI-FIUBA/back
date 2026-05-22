from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from src.application.auth.ports import PasswordHasherPort


class Argon2PasswordHasher(PasswordHasherPort):
    """Password hasher adapter backed by Argon2id."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher()

    def hash(self, plain_password: str) -> str:
        return self._hasher.hash(plain_password)

    def verify(self, plain_password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password_hash, plain_password)
        except (VerifyMismatchError, InvalidHashError, VerificationError):
            return False
