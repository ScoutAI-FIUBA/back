from __future__ import annotations

import hashlib
import hmac
import secrets

from src.application.auth.ports import RefreshTokenServicePort


class OpaqueRefreshTokenService(RefreshTokenServicePort):
    def __init__(self, *, secret: str) -> None:
        self._secret = secret.encode("utf-8")

    def generate_plain(self) -> str:
        return secrets.token_urlsafe(48)

    def hash(self, token: str) -> str:
        return hmac.new(self._secret, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def fingerprint(self, token: str) -> str:
        return self.hash(token)[:16]
