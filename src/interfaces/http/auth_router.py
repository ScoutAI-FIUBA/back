from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus

from fastapi import APIRouter, Cookie, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.application.auth.errors import AuthError, auth_error_http_status
from src.application.auth.use_cases import (
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


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


def _extract_bearer_token(authorization_header: str | None) -> str:
    if not authorization_header:
        raise AuthError(code="AUTH_UNAUTHORIZED", message="Missing authorization header")
    prefix = "Bearer "
    if not authorization_header.startswith(prefix):
        raise AuthError(code="AUTH_TOKEN_INVALID", message="Invalid authorization scheme")
    token = authorization_header[len(prefix) :].strip()
    if not token:
        raise AuthError(code="AUTH_TOKEN_INVALID", message="Missing bearer token")
    return token


def create_auth_router(
    *,
    register_use_case: RegisterUserUseCase,
    login_use_case: LoginUseCase,
    refresh_use_case: RefreshSessionUseCase,
    logout_use_case: LogoutUseCase,
    current_user_use_case: GetCurrentUserUseCase,
    access_token_resolver: Callable[[str], str],
) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/register", response_model=None)
    def register(payload: RegisterRequest):
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
        try:
            result = login_use_case.execute(LoginCommand(email=payload.email, password=payload.password))
            response.set_cookie(
                key="refresh_token",
                value=result.tokens.refresh_token,
                httponly=True,
                secure=True,
                samesite="strict",
                max_age=7 * 24 * 60 * 60,
                path="/auth",
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
        try:
            if not refresh_token:
                raise AuthError(code="AUTH_UNAUTHORIZED", message="Missing refresh cookie")
            result = refresh_use_case.execute(RefreshSessionCommand(refresh_token=refresh_token))
            response.set_cookie(
                key="refresh_token",
                value=result.tokens.refresh_token,
                httponly=True,
                secure=True,
                samesite="strict",
                max_age=7 * 24 * 60 * 60,
                path="/auth",
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
        try:
            if refresh_token:
                logout_use_case.execute(LogoutCommand(refresh_token=refresh_token))
            response.delete_cookie(key="refresh_token", path="/auth", secure=True, httponly=True, samesite="strict")
            response.status_code = HTTPStatus.NO_CONTENT
            return response
        except AuthError as exc:
            return JSONResponse(status_code=auth_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/me", response_model=None)
    def me(authorization: str | None = Header(default=None)):
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

    return router
