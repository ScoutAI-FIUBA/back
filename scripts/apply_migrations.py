from __future__ import annotations

import os
from pathlib import Path

import psycopg


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")

    migration_file = Path("src/infrastructure/auth/migrations/001_auth_foundation.sql")
    sql = migration_file.read_text(encoding="utf-8")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


if __name__ == "__main__":
    main()
