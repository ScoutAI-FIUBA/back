from __future__ import annotations

import unittest
from http import HTTPStatus

from src.application.auth.errors import (
    AUTH_EMAIL_ALREADY_EXISTS,
    AUTH_INTERNAL,
    AUTH_INVALID_CREDENTIALS,
    AUTH_UNAUTHORIZED,
    AUTH_VALIDATION_ERROR,
    AuthError,
    auth_error_http_status,
)


class TestErrors(unittest.TestCase):
    def test_codes_map_to_expected_status(self) -> None:
        self.assertEqual(auth_error_http_status(AUTH_EMAIL_ALREADY_EXISTS), HTTPStatus.CONFLICT)
        self.assertEqual(auth_error_http_status(AUTH_VALIDATION_ERROR), HTTPStatus.BAD_REQUEST)
        self.assertEqual(auth_error_http_status(AUTH_INVALID_CREDENTIALS), HTTPStatus.UNAUTHORIZED)
        self.assertEqual(auth_error_http_status(AUTH_UNAUTHORIZED), HTTPStatus.UNAUTHORIZED)
        self.assertEqual(auth_error_http_status(AUTH_INTERNAL), HTTPStatus.INTERNAL_SERVER_ERROR)

    def test_error_envelope_details_optional(self) -> None:
        without_details = AuthError(code=AUTH_UNAUTHORIZED, message="unauthorized").to_envelope()
        self.assertEqual(without_details, {"error": {"code": AUTH_UNAUTHORIZED, "message": "unauthorized"}})

        with_details = AuthError(
            code=AUTH_VALIDATION_ERROR,
            message="invalid payload",
            details={"field": "email"},
        ).to_envelope()
        self.assertEqual(with_details["error"]["details"], {"field": "email"})


if __name__ == "__main__":
    unittest.main()
