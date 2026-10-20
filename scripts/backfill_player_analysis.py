"""Keeps the player analysis rows for analyses that finished before the feature existed.

New jobs are synced automatically (when they finish and when the scout marks their team).
Run this once after deploying, and again whenever you want to rebuild everything:

    python scripts/backfill_player_analysis.py            # rebuild every finished job that has a team side
    python scripts/backfill_player_analysis.py --dry-run  # only list what would be rebuilt

It needs the same environment as the API (DATABASE_URL and the object storage settings), and
is safe to repeat: each video's rows are replaced, never added to.
"""

from __future__ import annotations

import argparse
import os

import psycopg

from src.interfaces.http.bootstrap.config import require_env
from src.interfaces.http.bootstrap.dependencies import build_http_dependencies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="list the jobs without changing anything")
    args = parser.parse_args()

    database_url = require_env("DATABASE_URL")
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text FROM processing_jobs
             WHERE status = 'DONE' AND our_team_side IS NOT NULL AND results_key IS NOT NULL
             ORDER BY created_at
            """
        )
        job_ids = [row[0] for row in cur.fetchall()]
    print(f"{len(job_ids)} finished jobs have a team side set")
    if args.dry_run:
        for job_id in job_ids:
            print(f"  would rebuild {job_id}")
        return

    deps = build_http_dependencies(
        jwt_secret=require_env("AUTH_JWT_SECRET"),
        refresh_secret=require_env("AUTH_REFRESH_SECRET"),
        jwt_issuer=require_env("AUTH_JWT_ISSUER"),
        jwt_audience=require_env("AUTH_JWT_AUDIENCE"),
        database_url=database_url,
    )
    kept_total, failed = 0, 0
    for job_id in job_ids:
        try:
            kept = deps.sync_player_analysis_use_case.execute(job_id)
        except Exception as exc:  # noqa: BLE001 - report and keep going, one bad job must not stop the rest
            failed += 1
            print(f"  {job_id}: FAILED {type(exc).__name__}: {exc}")
            continue
        kept_total += kept
        print(f"  {job_id}: {kept} shots kept")
    print(f"done: {kept_total} shots kept, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
