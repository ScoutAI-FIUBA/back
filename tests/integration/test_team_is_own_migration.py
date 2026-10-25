from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from scripts import apply_migrations


pytestmark = pytest.mark.integration

MIGRATION_NAME = "src/infrastructure/team/migrations/003_team_is_own.sql"


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for integration tests")
    return database_url


def test_is_own_migration_is_additive_and_can_run_twice() -> None:
    database_url = _database_url()
    apply_migrations.main()

    user_id = str(uuid4())
    plain_id = str(uuid4())
    own_id = str(uuid4())
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO users (id, email_normalized, password_hash, created_at, updated_at)
            VALUES (%s, %s, 'x', NOW(), NOW())
            """,
            (user_id, f"migration-{uuid4().hex}@example.com"),
        )
        # Written without is_own: the column default must make it a rival.
        conn.execute(
            """
            INSERT INTO teams (id, name, short_name, city, country, owner_user_id, created_at)
            VALUES (%s, 'Plain', 'PLN', 'Cordoba', 'Argentina', %s, NOW())
            """,
            (plain_id, user_id),
        )
        conn.execute(
            """
            INSERT INTO teams (id, name, short_name, city, country, owner_user_id, created_at, is_own)
            VALUES (%s, 'Own', 'OWN', 'Cordoba', 'Argentina', %s, NOW(), TRUE)
            """,
            (own_id, user_id),
        )
        conn.commit()

    select_rows = "SELECT * FROM teams WHERE id = ANY(%s) ORDER BY id"
    column_info = """
        SELECT is_nullable, column_default FROM information_schema.columns
        WHERE table_name = 'teams' AND column_name = 'is_own'
    """
    with psycopg.connect(database_url) as conn:
        assert conn.execute("SELECT is_own FROM teams WHERE id = %s", (plain_id,)).fetchone()[0] is False
        assert conn.execute("SELECT is_own FROM teams WHERE id = %s", (own_id,)).fetchone()[0] is True
        assert conn.execute(column_info).fetchone() == ("NO", "false")
        before = conn.execute(select_rows, ([plain_id, own_id],)).fetchall()
        count_before = conn.execute("SELECT count(*) FROM teams").fetchone()[0]
        conn.execute("DELETE FROM schema_migrations WHERE filename = %s", (MIGRATION_NAME,))
        conn.commit()

    apply_migrations.main()

    with psycopg.connect(database_url) as conn:
        assert conn.execute(select_rows, ([plain_id, own_id],)).fetchall() == before
        assert conn.execute("SELECT is_own FROM teams WHERE id = %s", (own_id,)).fetchone()[0] is True
        assert conn.execute("SELECT count(*) FROM teams").fetchone()[0] == count_before
        assert conn.execute(column_info).fetchone() == ("NO", "false")
        applied = conn.execute("SELECT 1 FROM schema_migrations WHERE filename = %s", (MIGRATION_NAME,)).fetchone()
        assert applied is not None
        conn.execute("DELETE FROM teams WHERE id = ANY(%s)", ([plain_id, own_id],))
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
