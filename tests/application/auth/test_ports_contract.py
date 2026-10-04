from __future__ import annotations

import unittest

from src.application.auth import ports


class TestPortsContract(unittest.TestCase):
    def test_expected_port_classes_exist(self) -> None:
        expected = {
            "UserRepositoryPort",
            "RefreshSessionRepositoryPort",
            "PasswordHasherPort",
            "TokenIssuerPort",
            "RefreshTokenServicePort",
            "ClockPort",
            "IdGeneratorPort",
            "UnitOfWorkPort",
            "EmailTokenRepositoryPort",
            "EmailSenderPort",
            "GoogleIdTokenVerifierPort",
        }
        present = {name for name in dir(ports) if name.endswith("Port")}
        self.assertTrue(expected.issubset(present))

    def test_ports_module_has_no_sql_keywords(self) -> None:
        source_path = "src/application/auth/ports.py"
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read().lower()
        forbidden = ["postgres", "psycopg", "sqlalchemy", "select ", "insert "]
        for token in forbidden:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
