from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.application.auth.errors import AUTH_VALIDATION_ERROR, AuthError, auth_error_http_status


def register_error_handlers(app: FastAPI) -> None:
    """Registers HTTP-layer error mapping handlers.

    Keeps FastAPI's default validation envelope for every route except ``/auth*``.
    Auth endpoints are intentionally normalized to the auth error contract so clients
    can always rely on ``AuthError.to_envelope()`` for authentication flows.
    """

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(request: Request, exc: RequestValidationError):
        """Maps request validation failures to the expected error envelope by boundary."""

        if request.url.path.startswith("/auth"):
            auth_error = AuthError(
                code=AUTH_VALIDATION_ERROR,
                message="Invalid auth payload",
                details={"errors": exc.errors()},
            )
            return JSONResponse(
                status_code=auth_error_http_status(auth_error.code),
                content=auth_error.to_envelope(),
            )
        return await request_validation_exception_handler(request, exc)
