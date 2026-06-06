from __future__ import annotations

"""Auth HTTP routes.

This router translates transport concerns (headers/cookies/status codes) into
application command/query objects and maps domain errors to HTTP responses.
"""

from collections.abc import Callable
from http import HTTPStatus

from fastapi import APIRouter, Cookie, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.application.auth.errors import AuthError, auth_error_http_status
from src.application.auth.use_cases import (
    DeleteCurrentUserCommand,
    DeleteCurrentUserUseCase,
    GetCurrentUserQuery,
    GetCurrentUserUseCase,
    LoginCommand,
    LoginUseCase,
    LogoutCommand,
    LogoutUseCase,
    RefreshSessionCommand,
    RefreshSessionUseCase,
    RegisterUserCommand,
    RegisterUserUseCase,
)
from src.interfaces.http.bootstrap.config import AuthCookieSameSite, auth_refresh_cookie_samesite


class RegisterRequest(BaseModel):
    """HTTP payload contract for user registration."""

    email: str = Field(min_length=3)
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    """HTTP payload contract for credential login."""

    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


def _extract_bearer_token(authorization_header: str | None) -> str:
    """Parses ``Authorization: Bearer <token>`` using auth-domain error codes.

    Raises:
        AuthError: AUTH_UNAUTHORIZED for missing header; AUTH_TOKEN_INVALID for
            malformed scheme or empty bearer token.
    """

    if not authorization_header:
        raise AuthError(code="AUTH_UNAUTHORIZED", message="Missing authorization header")
    prefix = "Bearer "
    if not authorization_header.startswith(prefix):
        raise AuthError(code="AUTH_TOKEN_INVALID", message="Invalid authorization scheme")
    token = authorization_header[len(prefix) :].strip()
    if not token:
        raise AuthError(code="AUTH_TOKEN_INVALID", message="Missing bearer token")
    return token


def _set_refresh_cookie(
    response: Response,
    *,
    refresh_token: str,
    samesite: AuthCookieSameSite,
    max_age: int = 7 * 24 * 60 * 60,
) -> None:
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite=samesite,
        max_age=max_age,
        path="/auth",
    )


def _clear_refresh_cookie(response: Response, *, samesite: AuthCookieSameSite) -> None:
    response.delete_cookie(
        key="refresh_token",
        path="/auth",
        secure=True,
        httponly=True,
        samesite=samesite,
    )


def create_auth_router(
    *,
    register_use_case: RegisterUserUseCase,
    login_use_case: LoginUseCase,
    refresh_use_case: RefreshSessionUseCase,
    logout_use_case: LogoutUseCase,
    current_user_use_case: GetCurrentUserUseCase,
    delete_current_user_use_case: DeleteCurrentUserUseCase,
    access_token_resolver: Callable[[str], str],
    refresh_cookie_samesite: AuthCookieSameSite | None = None,
) -> APIRouter:
    """Creates auth endpoints and maps application auth errors to HTTP envelopes.

    Security semantics:
    - Refresh tokens are only transported via secure, httpOnly cookies.
    - Access tokens are only accepted from ``Authorization: Bearer`` headers.
    """

    cookie_samesite = refresh_cookie_samesite or auth_refresh_cookie_samesite()
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/register", response_model=None)
    def register(payload: RegisterRequest):
        """Creates user credentials and returns auth identity envelope."""

        try:
            user = register_use_case.execute(
                RegisterUserCommand(email=payload.email, password=payload.password)
            )
            return {
                "user": {
                    "id": user.user_id,
                    "email": user.email,
                    "role": user.role,
                    "email_verified": user.email_verified,
                }
            }
        except AuthError as exc:
            return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    @router.post("/login", response_model=None)
    def login(payload: LoginRequest, response: Response):
        """Authenticates credentials and issues access+refresh tokens.

        Boundary ownership: refresh token is delivered only via secure cookie;
        access token is returned in response body for bearer-header usage.
        """

        try:
            result = login_use_case.execute(LoginCommand(email=payload.email, password=payload.password))
            _set_refresh_cookie(
                response,
                refresh_token=result.tokens.refresh_token,
                samesite=cookie_samesite,
            )
            return {
                "access_token": result.tokens.access_token,
                "token_type": result.tokens.token_type,
                "expires_in": result.tokens.expires_in,
                "user": {
                    "id": result.user.user_id,
                    "email": result.user.email,
                    "role": result.user.role,
                    "email_verified": result.user.email_verified,
                },
            }
        except AuthError as exc:
            return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    @router.post("/refresh", response_model=None)
    def refresh(response: Response, refresh_token: str | None = Cookie(default=None)):
        """Rotates refresh token and returns a fresh access token pair."""

        try:
            if not refresh_token:
                raise AuthError(code="AUTH_UNAUTHORIZED", message="Missing refresh cookie")
            result = refresh_use_case.execute(RefreshSessionCommand(refresh_token=refresh_token))
            _set_refresh_cookie(
                response,
                refresh_token=result.tokens.refresh_token,
                samesite=cookie_samesite,
            )
            return {
                "access_token": result.tokens.access_token,
                "token_type": result.tokens.token_type,
                "expires_in": result.tokens.expires_in,
                "user": {
                    "id": result.user.user_id,
                    "email": result.user.email,
                    "role": result.user.role,
                    "email_verified": result.user.email_verified,
                },
            }
        except AuthError as exc:
            return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    @router.post("/logout", response_model=None)
    def logout(response: Response, refresh_token: str | None = Cookie(default=None)):
        """Revokes current refresh session when present and clears auth cookie."""

        try:
            if refresh_token:
                logout_use_case.execute(LogoutCommand(refresh_token=refresh_token))
            _clear_refresh_cookie(response, samesite=cookie_samesite)
            response.status_code = HTTPStatus.NO_CONTENT
            return response
        except AuthError as exc:
            return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/me", response_model=None)
    def me(authorization: str | None = Header(default=None)):
        """Resolves bearer token to current auth identity."""

        try:
            token = _extract_bearer_token(authorization)
            user_id = access_token_resolver(token)
            user = current_user_use_case.execute(GetCurrentUserQuery(user_id=user_id))
            return {
                "user": {
                    "id": user.user_id,
                    "email": user.email,
                    "role": user.role,
                    "email_verified": user.email_verified,
                }
            }
        except AuthError as exc:
            return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    @router.delete("/me", response_model=None)
    def delete_me(authorization: str | None = Header(default=None)):
        """Soft-deletes current user account and invalidates refresh sessions."""

        try:
            token = _extract_bearer_token(authorization)
            user_id = access_token_resolver(token)
            delete_current_user_use_case.execute(DeleteCurrentUserCommand(user_id=user_id))
            return Response(status_code=HTTPStatus.NO_CONTENT)
        except AuthError as exc:
            return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    return router
