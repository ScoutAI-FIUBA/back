from __future__ import annotations

from src.application.auth.errors import AUTH_TOKEN_INVALID, AuthError
from src.application.auth.ports import GoogleIdentity, GoogleIdTokenVerifierPort


class UnconfiguredGoogleIdTokenVerifier(GoogleIdTokenVerifierPort):
    def verify(self, id_token: str) -> GoogleIdentity:
        raise AuthError(code=AUTH_TOKEN_INVALID, message="Google login is not configured")


class GoogleIdTokenVerifier(GoogleIdTokenVerifierPort):
    """Validates a Google ID token against the configured OAuth client."""

    def __init__(self, *, client_id: str) -> None:
        self._client_id = client_id

    def verify(self, id_token: str) -> GoogleIdentity:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token as google_id_token
        from google.auth.exceptions import GoogleAuthError

        try:
            claims = google_id_token.verify_oauth2_token(id_token, Request(), self._client_id)
        except (GoogleAuthError, ValueError) as exc:
            raise AuthError(code=AUTH_TOKEN_INVALID, message="Google token is invalid") from exc

        email = str(claims.get("email") or "").strip()
        subject = str(claims.get("sub") or "").strip()
        if not email or not subject:
            raise AuthError(code=AUTH_TOKEN_INVALID, message="Google token is missing identity claims")
        return GoogleIdentity(
            subject=subject,
            email=email,
            email_verified=bool(claims.get("email_verified")),
            full_name=str(claims.get("name") or "").strip() or None,
        )
