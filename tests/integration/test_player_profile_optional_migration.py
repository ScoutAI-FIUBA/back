from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from scripts import apply_migrations


pytestmark = pytest.mark.integration

MIGRATION_NAME = "src/infrastructure/players/migrations/004_player_profile_optional.sql"
OPTIONAL_COLUMNS = ("birth_date", "height_cm", "weight_kg", "primary_position")


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for integration tests")
    return database_url


def _nullable(conn: psycopg.Connection) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT column_name, is_nullable FROM information_schema.columns
        WHERE table_name = 'players' AND column_name = ANY(%s)
        """,
        (list(OPTIONAL_COLUMNS),),
    ).fetchall()
    return {name: nullable for name, nullable in rows}


def test_profile_migration_only_relaxes_constraints_and_can_run_twice() -> None:
    database_url = _database_url()
    apply_migrations.main()

    player_id = str(uuid4())
    user_id = str(uuid4())
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO users (id, email_normalized, password_hash, created_at, updated_at)
            VALUES (%s, %s, 'x', NOW(), NOW())
            """,
            (user_id, f"migration-{uuid4().hex}@example.com"),
        )
        conn.execute(
            """
            INSERT INTO players (id, first_name, last_name, birth_date, height_cm, weight_kg,
                                 primary_position, owner_user_id)
            VALUES (%s, 'Full', 'Profile', '2000-01-02', 190, 85, 'PG', %s)
            """,
            (player_id, user_id),
        )
        conn.commit()

    with psycopg.connect(database_url) as conn:
        assert _nullable(conn) == {column: "YES" for column in OPTIONAL_COLUMNS}
        select_row = "SELECT * FROM players WHERE id = %s"
        before = conn.execute(select_row, (player_id,)).fetchone()
        count_before = conn.execute("SELECT count(*) FROM players").fetchone()[0]
        conn.execute("DELETE FROM schema_migrations WHERE filename = %s", (MIGRATION_NAME,))
        conn.commit()

    apply_migrations.main()

    with psycopg.connect(database_url) as conn:
        assert _nullable(conn) == {column: "YES" for column in OPTIONAL_COLUMNS}
        assert conn.execute(select_row, (player_id,)).fetchone() == before
        assert conn.execute("SELECT count(*) FROM players").fetchone()[0] == count_before
        applied = conn.execute("SELECT 1 FROM schema_migrations WHERE filename = %s", (MIGRATION_NAME,)).fetchone()
        assert applied is not None
        conn.execute("DELETE FROM players WHERE id = %s", (player_id,))
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
