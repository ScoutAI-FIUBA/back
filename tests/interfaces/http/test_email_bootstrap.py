from __future__ import annotations

import unittest

from src.interfaces.http.bootstrap.dependencies import _app_public_url, _build_email_sender
from src.infrastructure.auth.brevo_email_sender import BrevoEmailSender
from src.infrastructure.auth.resend_email_sender import NoOpEmailSender


class TestEmailBootstrap(unittest.TestCase):
    def test_app_public_url_prefers_explicit_env(self) -> None:
        with self._env(
            APP_PUBLIC_URL="https://front.example/",
            CORS_ORIGINS="https://other.example",
        ):
            self.assertEqual(_app_public_url(), "https://front.example")

    def test_app_public_url_falls_back_to_cors_origin(self) -> None:
        with self._env(APP_PUBLIC_URL="", CORS_ORIGINS="https://scoutai-front.onrender.com,http://localhost:5173"):
            self.assertEqual(_app_public_url(), "https://scoutai-front.onrender.com")

    def test_app_public_url_defaults_to_local_vite(self) -> None:
        with self._env(APP_PUBLIC_URL="", CORS_ORIGINS=""):
            self.assertEqual(_app_public_url(), "http://localhost:5173")

    def test_brevo_without_from_address_is_noop(self) -> None:
        with self._env(BREVO_API_KEY="key", BREVO_FROM_ADDRESS="", SMTP_FROM_ADDRESS=""):
            self.assertIsInstance(_build_email_sender(), NoOpEmailSender)

    def test_brevo_with_from_address_is_selected(self) -> None:
        with self._env(BREVO_API_KEY="key", BREVO_FROM_ADDRESS="ScoutAI <a@b.com>"):
            self.assertIsInstance(_build_email_sender(), BrevoEmailSender)

    def _env(self, **values: str):
        import os
        from contextlib import contextmanager

        @contextmanager
        def managed():
            previous = {key: os.environ.get(key) for key in values}
            try:
                for key, value in values.items():
                    if value == "":
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                yield
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

        return managed()


if __name__ == "__main__":
    unittest.main()
