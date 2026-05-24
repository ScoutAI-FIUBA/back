from __future__ import annotations

import os

import psycopg
import pytest


@pytest.mark.integration
def test_database_is_reachable_and_auth_tables_exist() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.fail("DATABASE_URL is required for integration tests")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass('public.users'), to_regclass('public.auth_refresh_sessions'), to_regclass('public.players')"
            )
            users_table, refresh_sessions_table, players_table = cur.fetchone()

    assert users_table == "users"
    assert refresh_sessions_table == "auth_refresh_sessions"
    assert players_table == "players"
