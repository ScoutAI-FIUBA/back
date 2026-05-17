from __future__ import annotations

import os
import time

import psycopg


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")

    timeout_seconds = int(os.getenv("DB_WAIT_TIMEOUT_SECONDS", "60"))
    interval_seconds = float(os.getenv("DB_WAIT_INTERVAL_SECONDS", "2"))
    started_at = time.time()

    while True:
        try:
            with psycopg.connect(database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            return
        except psycopg.OperationalError:
            if (time.time() - started_at) >= timeout_seconds:
                raise RuntimeError(f"Database not ready after {timeout_seconds} seconds")
            time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
