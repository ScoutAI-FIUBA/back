from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import datetime, timezone

from src.application.auth.errors import AUTH_TOKEN_EXPIRED, AUTH_TOKEN_INVALID, AuthError


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode((raw + padding).encode("utf-8"))


class JWTAccessTokenResolver:
    def __init__(self, *, secret: str, issuer: str, audience: str) -> None:
        self._secret = secret.encode("utf-8")
        self._issuer = issuer
        self._audience = audience

    def resolve_subject(self, token: str) -> str:
        try:
            header_b64, payload_b64, signature_b64 = token.split(".")
            signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
            expected = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
            presented = _b64url_decode(signature_b64)
            if not hmac.compare_digest(expected, presented):
                raise AuthError(code=AUTH_TOKEN_INVALID, message="Invalid token signature")

            payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        except ValueError as exc:
            raise AuthError(code=AUTH_TOKEN_INVALID, message="Malformed token") from exc
        except binascii.Error as exc:
            raise AuthError(code=AUTH_TOKEN_INVALID, message="Malformed token") from exc
        except json.JSONDecodeError as exc:
            raise AuthError(code=AUTH_TOKEN_INVALID, message="Malformed token payload") from exc

        for key in ("sub", "iss", "aud", "iat", "exp", "jti"):
            if key not in payload:
                raise AuthError(code=AUTH_TOKEN_INVALID, message=f"Missing token claim: {key}")

        if payload["iss"] != self._issuer or payload["aud"] != self._audience:
            raise AuthError(code=AUTH_TOKEN_INVALID, message="Invalid token issuer or audience")

        now_ts = int(datetime.now(timezone.utc).timestamp())
        if int(payload["exp"]) <= now_ts:
            raise AuthError(code=AUTH_TOKEN_EXPIRED, message="Token expired")

        return str(payload["sub"])
