from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.infrastructure.stats.postgres_catch_up_lock import PostgresCatchUpLock
from src.interfaces.http.bootstrap.dependencies import OperationConnection


class TestNoPreparedStatements(unittest.TestCase):
    """The pooled Supabase connection breaks psycopg's automatic prepared statements."""

    def test_operation_connection_disables_prepared_statements(self) -> None:
        with patch("psycopg.connect", return_value=MagicMock()) as connect:
            with OperationConnection("postgresql://x/y").cursor():
                pass
            with OperationConnection("postgresql://x/y").transaction():
                pass
        self.assertEqual(connect.call_count, 2)
        for call in connect.call_args_list:
            self.assertIs(call.kwargs.get("prepare_threshold", "missing"), None)

    def test_catch_up_lock_disables_prepared_statements(self) -> None:
        with patch("psycopg.connect", return_value=MagicMock()) as connect:
            with PostgresCatchUpLock("postgresql://x/y").try_acquire():
                pass
        self.assertIs(connect.call_args.kwargs.get("prepare_threshold", "missing"), None)
