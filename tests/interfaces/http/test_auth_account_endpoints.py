from __future__ import annotations

from http import HTTPStatus
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.auth.use_cases import (
    RequestPasswordResetCommand,
    ResetPasswordCommand,
)
from src.interfaces.http.routes.auth_router import create_auth_router


class _Forgot:
    def __init__(self) -> None:
        self.emails: list[str] = []

    def execute(self, command: RequestPasswordResetCommand) -> None:
        self.emails.append(command.email)


class _Reset:
    def __init__(self) -> None:
        self.calls: list[ResetPasswordCommand] = []

    def execute(self, command: ResetPasswordCommand) -> None:
        self.calls.append(command)


class _Unused:
    def execute(self, *args, **kwargs):
        raise AssertionError("should not be called")


class TestAuthAccountEndpoints(unittest.TestCase):
    def test_forgot_password_is_accepted_without_auth(self) -> None:
        forgot = _Forgot()
        router = create_auth_router(
            register_use_case=_Unused(),
            login_use_case=_Unused(),
            refresh_use_case=_Unused(),
            logout_use_case=_Unused(),
            current_user_use_case=_Unused(),
            delete_current_user_use_case=_Unused(),
            access_token_resolver=lambda _: "user-1",
            request_password_reset_use_case=forgot,
        )
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            response = client.post("/auth/password/forgot", json={"email": "user@example.com"})
        self.assertEqual(response.status_code, HTTPStatus.ACCEPTED)
        self.assertEqual(forgot.emails, ["user@example.com"])

    def test_reset_password_returns_no_content(self) -> None:
        reset = _Reset()
        router = create_auth_router(
            register_use_case=_Unused(),
            login_use_case=_Unused(),
            refresh_use_case=_Unused(),
            logout_use_case=_Unused(),
            current_user_use_case=_Unused(),
            delete_current_user_use_case=_Unused(),
            access_token_resolver=lambda _: "user-1",
            reset_password_use_case=reset,
        )
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            response = client.post(
                "/auth/password/reset",
                json={"token": "abc", "password": "newsecret1"},
            )
        self.assertEqual(response.status_code, HTTPStatus.NO_CONTENT)
        self.assertEqual(reset.calls[0].token, "abc")
