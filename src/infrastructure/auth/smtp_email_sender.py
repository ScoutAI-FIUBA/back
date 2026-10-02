from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from src.application.auth.errors import AUTH_INTERNAL, AuthError
from src.application.auth.ports import EmailSenderPort

logger = logging.getLogger(__name__)


class SmtpEmailSender(EmailSenderPort):
    """Sends mail through SMTP. Gmail works without a custom domain."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_address: str,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_address = from_address

    def send(self, *, to: str, subject: str, html: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._from_address
        message["To"] = to
        message.set_content("Abrí este mail en un cliente que muestre HTML para usar el enlace.")
        message.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(self._host, self._port, timeout=15) as smtp:
                smtp.starttls()
                smtp.login(self._username, self._password)
                smtp.send_message(message)
        except (OSError, TimeoutError, smtplib.SMTPException) as exc:
            logger.exception("SMTP send failed")
            raise AuthError(code=AUTH_INTERNAL, message="Failed to send email") from exc
