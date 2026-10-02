from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.infrastructure.auth.smtp_email_sender import SmtpEmailSender


class TestSmtpEmailSender(unittest.TestCase):
    def test_sends_html_through_starttls(self) -> None:
        sender = SmtpEmailSender(
            host="smtp.gmail.com",
            port=587,
            username="scout@gmail.com",
            password="app-password",
            from_address="ScoutAI <scout@gmail.com>",
        )
        smtp = MagicMock()
        with patch("src.infrastructure.auth.smtp_email_sender.smtplib.SMTP", return_value=smtp) as factory:
            sender.send(to="user@example.com", subject="Reset", html="<p>link</p>")
        factory.assert_called_once_with("smtp.gmail.com", 587, timeout=15)
        smtp.__enter__.return_value.starttls.assert_called_once()
        smtp.__enter__.return_value.login.assert_called_once_with("scout@gmail.com", "app-password")
        smtp.__enter__.return_value.send_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
