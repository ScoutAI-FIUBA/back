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
    ChangePasswordCommand,
    ChangePasswordUseCase,
    ConfirmEmailVerificationCommand,
    ConfirmEmailVerificationUseCase,
    DeleteCurrentUserCommand,
    DeleteCurrentUserUseCase,
    GetCurrentUserQuery,
    GetCurrentUserUseCase,
    GoogleLoginCommand,
    GoogleLoginUseCase,
    LoginCommand,
    LoginUseCase,
    LogoutCommand,
    LogoutUseCase,
    RefreshSessionCommand,
    RefreshSessionUseCase,
    RegisterUserCommand,
    RegisterUserUseCase,
    RequestPasswordResetCommand,
    RequestPasswordResetUseCase,
    ResetPasswordCommand,
    ResetPasswordUseCase,
    SendEmailVerificationCommand,
    SendEmailVerificationUseCase,
    UpdateProfileCommand,
    UpdateProfileUseCase,
)
from src.domain.auth.value_objects import AuthIdentity
from src.interfaces.http.bootstrap.config import AuthCookieSameSite, auth_refresh_cookie_samesite


class RegisterRequest(BaseModel):
    """HTTP payload contract for user registration."""

    email: str = Field(min_length=3)
    password: str = Field(min_length=8)
    full_name: str | None = Field(default=None, max_length=120)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=8)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class UpdateProfileRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)


class ConfirmEmailRequest(BaseModel):
    token: str = Field(min_length=1)


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(min_length=1)


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


def _user_payload(user: AuthIdentity) -> dict[str, object]:
    return {
        "id": user.user_id,
        "email": user.email,
        "role": user.role,
        "email_verified": user.email_verified,
        "full_name": user.full_name,
    }


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
    request_password_reset_use_case: RequestPasswordResetUseCase | None = None,
    reset_password_use_case: ResetPasswordUseCase | None = None,
    change_password_use_case: ChangePasswordUseCase | None = None,
    update_profile_use_case: UpdateProfileUseCase | None = None,
    send_email_verification_use_case: SendEmailVerificationUseCase | None = None,
    confirm_email_verification_use_case: ConfirmEmailVerificationUseCase | None = None,
    google_login_use_case: GoogleLoginUseCase | None = None,
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
                RegisterUserCommand(
                    email=payload.email,
                    password=payload.password,
                    full_name=getattr(payload, "full_name", None),
                )
            )
            if send_email_verification_use_case is not None:
                try:
                    send_email_verification_use_case.execute(
                        SendEmailVerificationCommand(user_id=user.user_id)
                    )
                except AuthError:
                    pass
            return {"user": _user_payload(user)}
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
                "user": _user_payload(result.user),
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
                "user": _user_payload(result.user),
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
            return {"user": _user_payload(user)}
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

    if request_password_reset_use_case is not None:

        @router.post("/password/forgot", status_code=HTTPStatus.ACCEPTED, response_model=None)
        def forgot_password(payload: ForgotPasswordRequest):
            try:
                request_password_reset_use_case.execute(RequestPasswordResetCommand(email=payload.email))
            except AuthError:
                pass
            return Response(status_code=HTTPStatus.ACCEPTED)

    if reset_password_use_case is not None:

        @router.post("/password/reset", status_code=HTTPStatus.NO_CONTENT, response_model=None)
        def reset_password(payload: ResetPasswordRequest):
            try:
                reset_password_use_case.execute(
                    ResetPasswordCommand(token=payload.token, password=payload.password)
                )
                return Response(status_code=HTTPStatus.NO_CONTENT)
            except AuthError as exc:
                return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    if change_password_use_case is not None:

        @router.put("/me/password", status_code=HTTPStatus.NO_CONTENT, response_model=None)
        def change_password(payload: ChangePasswordRequest, authorization: str | None = Header(default=None)):
            try:
                token = _extract_bearer_token(authorization)
                user_id = access_token_resolver(token)
                change_password_use_case.execute(
                    ChangePasswordCommand(
                        user_id=user_id,
                        current_password=payload.current_password,
                        new_password=payload.new_password,
                    )
                )
                return Response(status_code=HTTPStatus.NO_CONTENT)
            except AuthError as exc:
                return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    if update_profile_use_case is not None:

        @router.patch("/me", response_model=None)
        def update_profile(payload: UpdateProfileRequest, authorization: str | None = Header(default=None)):
            try:
                token = _extract_bearer_token(authorization)
                user_id = access_token_resolver(token)
                user = update_profile_use_case.execute(
                    UpdateProfileCommand(user_id=user_id, full_name=payload.full_name)
                )
                return {"user": _user_payload(user)}
            except AuthError as exc:
                return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    if send_email_verification_use_case is not None:

        @router.post("/email/verify/send", status_code=HTTPStatus.ACCEPTED, response_model=None)
        def send_email_verification(authorization: str | None = Header(default=None)):
            try:
                token = _extract_bearer_token(authorization)
                user_id = access_token_resolver(token)
                send_email_verification_use_case.execute(SendEmailVerificationCommand(user_id=user_id))
                return Response(status_code=HTTPStatus.ACCEPTED)
            except AuthError as exc:
                return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    if confirm_email_verification_use_case is not None:

        @router.post("/email/verify/confirm", response_model=None)
        def confirm_email_verification(payload: ConfirmEmailRequest):
            try:
                user = confirm_email_verification_use_case.execute(
                    ConfirmEmailVerificationCommand(token=payload.token)
                )
                return {"user": _user_payload(user)}
            except AuthError as exc:
                return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    if google_login_use_case is not None:

        @router.post("/oauth/google", response_model=None)
        def google_login(payload: GoogleLoginRequest, response: Response):
            try:
                result = google_login_use_case.execute(GoogleLoginCommand(id_token=payload.id_token))
                _set_refresh_cookie(
                    response,
                    refresh_token=result.tokens.refresh_token,
                    samesite=cookie_samesite,
                )
                return {
                    "access_token": result.tokens.access_token,
                    "token_type": result.tokens.token_type,
                    "expires_in": result.tokens.expires_in,
                    "user": _user_payload(result.user),
                }
            except AuthError as exc:
                return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    return router

