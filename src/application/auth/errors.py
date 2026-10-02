from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Any


AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
AUTH_TOKEN_INVALID = "AUTH_TOKEN_INVALID"
AUTH_REFRESH_REUSED = "AUTH_REFRESH_REUSED"
AUTH_UNAUTHORIZED = "AUTH_UNAUTHORIZED"
AUTH_EMAIL_ALREADY_EXISTS = "AUTH_EMAIL_ALREADY_EXISTS"
AUTH_VALIDATION_ERROR = "AUTH_VALIDATION_ERROR"
AUTH_RATE_LIMITED = "AUTH_RATE_LIMITED"
AUTH_INTERNAL = "AUTH_INTERNAL"


@dataclass
class AuthError(Exception):
    code: str
    message: str
    details: dict[str, Any] | None = None

    def to_envelope(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return {"error": payload}


def auth_error_http_status(code: str) -> int:
    if code == AUTH_EMAIL_ALREADY_EXISTS:
        return HTTPStatus.CONFLICT
    if code == AUTH_VALIDATION_ERROR:
        return HTTPStatus.BAD_REQUEST
    if code == AUTH_RATE_LIMITED:
        return HTTPStatus.TOO_MANY_REQUESTS
    if code in {
        AUTH_INVALID_CREDENTIALS,
        AUTH_TOKEN_EXPIRED,
        AUTH_TOKEN_INVALID,
        AUTH_REFRESH_REUSED,
        AUTH_UNAUTHORIZED,
    }:
        return HTTPStatus.UNAUTHORIZED
    return HTTPStatus.INTERNAL_SERVER_ERROR
