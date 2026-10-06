from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from src.infrastructure.video.postgres_video_repository import PostgresVideoRepository


pytestmark = pytest.mark.integration


# Mirror scripts/apply_migrations.py order so the schema matches CI/production.
# The ownership migration adds the NOT NULL teams.owner_user_id column, so it
# must be applied for direct INSERTs into teams to be valid.
MIGRATION_DIRS = [
    Path("src/infrastructure/auth/migrations"),
    Path("src/infrastructure/players/migrations"),
    Path("src/infrastructure/team/migrations"),
    Path("src/infrastructure/matches/migrations"),
    Path("src/infrastructure/video/migrations"),
    Path("src/infrastructure/clip_collections/migrations"),
    Path("src/infrastructure/jobs/migrations"),
    Path("src/infrastructure/ownership/migrations"),
]


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for integration tests")
    return database_url


@pytest.fixture(scope="module", autouse=True)
def _schema_ready() -> None:
    database_url = _database_url()
    try:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                for migration_dir in MIGRATION_DIRS:
                    for migration_file in sorted(migration_dir.glob("*.sql")):
                        cur.execute(migration_file.read_text(encoding="utf-8"))
            conn.commit()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable for integration tests: {exc}")


def test_set_thumbnail_key_persists_and_reads_back() -> None:
    database_url = _database_url()
    team_id = str(uuid4())
    video_id = str(uuid4())
    user_id = f"thumb-user-{uuid4().hex}"
    storage_key = f"videos/{team_id}/{video_id}"
    thumbnail_key = f"thumbnails/{team_id}/{video_id}.jpg"
    now = datetime.now(timezone.utc)

    try:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, email_normalized, password_hash, email_verified, created_at, updated_at)
                    VALUES (%s, %s, %s, TRUE, %s, %s)
                    """,
                    (user_id, f"{user_id}@example.com", "not-a-real-hash", now, now),
                )
                cur.execute(
                    """
                    INSERT INTO teams (id, name, short_name, city, country, owner_user_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (team_id, "Thumb Team", "TT", "Buenos Aires", "Argentina", user_id, now),
                )
                cur.execute(
                    """
                    INSERT INTO videos (id, team_id, owner_user_id, storage_key, title, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (video_id, team_id, user_id, storage_key, "Thumb Video", "READY", now, now),
                )
            conn.commit()

            repository = PostgresVideoRepository(connection=conn)
            updated = repository.set_thumbnail_key(
                video_id=video_id,
                team_id=team_id,
                thumbnail_key=thumbnail_key,
            )
            assert updated is not None
            assert updated.thumbnail_key == thumbnail_key

            fetched = repository.get_by_id(video_id=video_id, team_id=team_id)
            assert fetched is not None
            assert fetched.thumbnail_key == thumbnail_key
    finally:
        with suppress(Exception):
            with psycopg.connect(database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM videos WHERE id = %s::uuid", (video_id,))
                    cur.execute("DELETE FROM teams WHERE id = %s::uuid", (team_id,))
                    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                conn.commit()
