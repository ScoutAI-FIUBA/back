from __future__ import annotations

import logging

import httpx

from src.application.auth.errors import AUTH_INTERNAL, AuthError
from src.application.auth.ports import EmailSenderPort

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class NoOpEmailSender(EmailSenderPort):
    """Used when no mail provider is configured. Forgot-password still succeeds."""

    def send(self, *, to: str, subject: str, html: str) -> None:
        logger.info("Email skipped: neither SMTP nor RESEND_API_KEY is configured")


class ResendEmailSender(EmailSenderPort):
    """Sends transactional mail through Resend's HTTP API."""

    def __init__(self, *, api_key: str, from_address: str) -> None:
        self._api_key = api_key
        self._from_address = from_address

    def send(self, *, to: str, subject: str, html: str) -> None:
        try:
            response = httpx.post(
                RESEND_API_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "from": self._from_address,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            logger.exception("Resend request failed")
            raise AuthError(code=AUTH_INTERNAL, message="Failed to send email") from exc
        if response.status_code >= 400:
            logger.error("Resend rejected the message: %s", response.status_code)
            raise AuthError(code=AUTH_INTERNAL, message="Failed to send email")
