from __future__ import annotations

import logging
from contextlib import contextmanager

import psycopg

from src.application.stats.player_analysis import CatchUpLockPort

logger = logging.getLogger(__name__)

# Fixed key shared by every worker and instance (arbitrary; no other advisory lock uses it).
CATCH_UP_LOCK_KEY = 7_005_110_207


class PostgresCatchUpLock(CatchUpLockPort):
    """Transaction-level advisory lock on a connection of its own, held for the whole run.

    The transaction stays open (idle, read committed: it holds no snapshot) until the run ends, then
    is rolled back and the connection closed in `finally`; the server also drops it if the process
    dies. A transaction lock, not a session lock, so it behaves the same behind a transaction pooler
    (Supabase port 6543), where a session lock would stay with a connection other clients reuse.
    Never raises: when the database cannot be reached it yields False.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @contextmanager
    def try_acquire(self):
        try:
            connection = psycopg.connect(self._dsn)
        except Exception:  # noqa: BLE001 - the catch-up is best effort
            logger.exception("Could not connect to take the player stats catch-up lock")
            yield False
            return
        try:
            row = connection.execute("SELECT pg_try_advisory_xact_lock(%(k)s)", {"k": CATCH_UP_LOCK_KEY}).fetchone()
            acquired = bool(row and row[0])
            if not acquired:
                logger.info("Player stats catch-up lock not acquired: another run is in progress")
            yield acquired
        finally:
            try:
                connection.rollback()
            finally:
                connection.close()
