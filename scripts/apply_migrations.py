from __future__ import annotations

import os
from pathlib import Path

import psycopg


# Without this table every file re-runs on each container start, which the
# Dockerfile does on every deploy. Keyed by relative path, not filename: each
# migrations directory numbers its files from 001.
TRACKING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")

    migration_dirs = [
        Path("src/infrastructure/auth/migrations"),
        # The players table is created by the auth migrations, so this must run after them.
        Path("src/infrastructure/players/migrations"),
        Path("src/infrastructure/team/migrations"),
        Path("src/infrastructure/matches/migrations"),
        Path("src/infrastructure/video/migrations"),
        Path("src/infrastructure/clip_collections/migrations"),
        # Jobs reference videos, teams and users, so this must run after them.
        Path("src/infrastructure/jobs/migrations"),
        Path("src/infrastructure/ownership/migrations"),
    ]
    migration_files = [migration for directory in migration_dirs for migration in sorted(directory.glob("*.sql"))]

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(TRACKING_TABLE_SQL)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT filename FROM schema_migrations")
            already_applied = {row[0] for row in cur.fetchall()}

        for migration_file in migration_files:
            name = migration_file.as_posix()
            if name in already_applied:
                continue
            # One transaction per file, so a failure half way through a deploy
            # leaves the earlier migrations applied and recorded instead of
            # rolling the whole run back.
            with conn.cursor() as cur:
                cur.execute(migration_file.read_text(encoding="utf-8"))
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%(filename)s)",
                    {"filename": name},
                )
            conn.commit()
            print(f"applied {name}")


if __name__ == "__main__":
    main()
