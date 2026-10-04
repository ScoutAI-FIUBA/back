from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.infrastructure.auth.brevo_email_sender import BrevoEmailSender, _split_from_address


class TestBrevoEmailSender(unittest.TestCase):
    def test_parses_named_from_address(self) -> None:
        name, email = _split_from_address("ScoutAI <scout@gmail.com>")
        self.assertEqual(name, "ScoutAI")
        self.assertEqual(email, "scout@gmail.com")

    def test_posts_transactional_email(self) -> None:
        sender = BrevoEmailSender(api_key="key", from_address="ScoutAI <scout@gmail.com>")
        response = MagicMock()
        response.status_code = 201
        with patch("src.infrastructure.auth.brevo_email_sender.httpx.post", return_value=response) as post:
            sender.send(to="user@example.com", subject="Reset", html="<p>link</p>")
        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["sender"], {"email": "scout@gmail.com", "name": "ScoutAI"})
        self.assertEqual(payload["to"], [{"email": "user@example.com"}])


if __name__ == "__main__":
    unittest.main()
