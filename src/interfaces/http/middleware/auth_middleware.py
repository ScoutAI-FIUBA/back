from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from src.application.auth.errors import AuthError, auth_error_http_status

PUBLIC_ROUTES = frozenset(
    {
        "/health",
        "/db-health",
        "/auth/register",
        "/auth/login",
        "/auth/refresh",
    }
)


def create_require_authenticated_user_middleware(
    *,
    resolve_subject: Callable[[str], str],
    public_routes: frozenset[str] = PUBLIC_ROUTES,
) -> Callable[[Request, Callable[[Request], Awaitable]], Awaitable]:
    """Builds auth guard middleware for protected HTTP routes.

    Contract:
    - Skips auth for ``OPTIONS`` and known public endpoints.
    - Requires ``Authorization: Bearer <token>`` everywhere else.
    - Stores the resolved authenticated subject in ``request.state.user_id``.
    - Converts domain auth failures to the shared auth error envelope.
    """

    async def require_authenticated_user(request: Request, call_next):
        """Enforces bearer auth and propagates user identity through request state."""

        if request.method == "OPTIONS" or request.url.path in public_routes:
            return await call_next(request)

        authorization_header = request.headers.get("authorization")
        if not authorization_header:
            auth_error = AuthError(
                code="AUTH_UNAUTHORIZED",
                message="Missing authorization header",
            )
            return JSONResponse(
                status_code=auth_error_http_status(auth_error.code),
                content=auth_error.to_envelope(),
            )

        prefix = "Bearer "
        if not authorization_header.startswith(prefix):
            auth_error = AuthError(
                code="AUTH_TOKEN_INVALID",
                message="Invalid authorization scheme",
            )
            return JSONResponse(
                status_code=auth_error_http_status(auth_error.code),
                content=auth_error.to_envelope(),
            )

        token = authorization_header[len(prefix) :].strip()
        if not token:
            auth_error = AuthError(
                code="AUTH_TOKEN_INVALID",
                message="Missing bearer token",
            )
            return JSONResponse(
                status_code=auth_error_http_status(auth_error.code),
                content=auth_error.to_envelope(),
            )

        try:
            request.state.user_id = resolve_subject(token)
        except AuthError as exc:
            return JSONResponse(
                status_code=auth_error_http_status(exc.code),
                content=exc.to_envelope(),
            )

        return await call_next(request)

    return require_authenticated_user
