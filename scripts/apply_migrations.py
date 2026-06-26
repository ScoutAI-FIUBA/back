from __future__ import annotations

import os
from pathlib import Path

import psycopg


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")

    migration_dirs = [
        Path("src/infrastructure/auth/migrations"),
        Path("src/infrastructure/team/migrations"),
        Path("src/infrastructure/video/migrations"),
        Path("src/infrastructure/clip_collections/migrations"),
    ]
    migration_files = [migration for directory in migration_dirs for migration in sorted(directory.glob("*.sql"))]

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for migration_file in migration_files:
                sql = migration_file.read_text(encoding="utf-8")
                cur.execute(sql)
        conn.commit()


if __name__ == "__main__":
    main()
