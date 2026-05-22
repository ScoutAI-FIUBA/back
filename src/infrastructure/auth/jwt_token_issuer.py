from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json

from src.application.auth.ports import TokenIssuerPort
from src.domain.auth.value_objects import AuthIdentity


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("utf-8")


class JWTTokenIssuer(TokenIssuerPort):
    def __init__(self, *, secret: str, issuer: str, audience: str) -> None:
        self._secret = secret.encode("utf-8")
        self._issuer = issuer
        self._audience = audience

    def issue_access(self, identity: AuthIdentity, jti: str, expires_at: datetime) -> str:
        now = datetime.now(timezone.utc)
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sub": identity.user_id,
            "iss": self._issuer,
            "aud": self._audience,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": jti,
            "role": identity.role,
            "email_verified": identity.email_verified,
        }

        encoded_header = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
        signature = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        encoded_signature = _b64url_encode(signature)
        return f"{encoded_header}.{encoded_payload}.{encoded_signature}"
