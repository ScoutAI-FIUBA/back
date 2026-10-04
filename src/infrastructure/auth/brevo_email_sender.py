from __future__ import annotations

import logging
import re

import httpx

from src.application.auth.errors import AUTH_INTERNAL, AuthError
from src.application.auth.ports import EmailSenderPort

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
_FROM_WITH_NAME = re.compile(r"^(?P<name>.+?)\s*<(?P<email>[^>]+)>$")


def _split_from_address(address: str) -> tuple[str | None, str]:
    match = _FROM_WITH_NAME.match(address.strip())
    if match:
        return match.group("name").strip().strip('"') or None, match.group("email").strip()
    return None, address.strip()


class BrevoEmailSender(EmailSenderPort):
    """Sends mail through Brevo's HTTPS API.

    Render blocks SMTP; this uses port 443. A single verified sender email is
    enough to deliver to any inbox — no DNS records.
    """

    def __init__(self, *, api_key: str, from_address: str) -> None:
        self._api_key = api_key
        name, email = _split_from_address(from_address)
        self._sender: dict[str, str] = {"email": email}
        if name:
            self._sender["name"] = name

    def send(self, *, to: str, subject: str, html: str) -> None:
        try:
            response = httpx.post(
                BREVO_API_URL,
                headers={
                    "api-key": self._api_key,
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                json={
                    "sender": self._sender,
                    "to": [{"email": to}],
                    "subject": subject,
                    "htmlContent": html,
                },
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            logger.exception("Brevo request failed")
            raise AuthError(code=AUTH_INTERNAL, message="Failed to send email") from exc
        if response.status_code >= 400:
            logger.error("Brevo rejected the message: %s %s", response.status_code, response.text)
            raise AuthError(code=AUTH_INTERNAL, message="Failed to send email")
