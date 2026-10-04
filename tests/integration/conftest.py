from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest


# Compose service name, CI service container with a mapped port, and a plain
# local install. Anything else is somebody's real database.
LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db"})

REMOTE_DATABASE_OPT_IN = "INTEGRATION_DB_ALLOW_REMOTE"


@pytest.fixture(scope="session", autouse=True)
def _refuse_remote_database() -> None:
    """Abort the run unless DATABASE_URL points at a local database.

    Every module here truncates `users` with CASCADE, which empties every table
    in the schema. The target is whatever DATABASE_URL happens to hold, so a
    single exported production URL is enough to destroy that database.

    Fails rather than skips: a skipped suite looks the same as a passing one,
    which is exactly how a misdirected run goes unnoticed.
    """

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return

    host = urlsplit(database_url).hostname or ""
    if host in LOCAL_DATABASE_HOSTS or os.getenv(REMOTE_DATABASE_OPT_IN) == "1":
        return

    pytest.fail(
        f"Refusing to run destructive integration tests against non-local host {host!r}. "
        f"Point DATABASE_URL at the local database, or set {REMOTE_DATABASE_OPT_IN}=1 to override.",
        pytrace=False,
    )
