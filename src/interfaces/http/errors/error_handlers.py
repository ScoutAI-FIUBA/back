from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.application.auth.errors import AUTH_VALIDATION_ERROR, AuthError, auth_error_http_status


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(request: Request, exc: RequestValidationError):
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
