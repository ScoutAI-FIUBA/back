from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

from src.application.jobs.ports import ActiveJobExistsError
from src.domain.jobs.entities import JobStatus, ProcessingJob


class CursorLike(Protocol):
    def execute(self, query: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> Any: ...

    def fetchone(self) -> dict[str, Any] | tuple[Any, ...] | None: ...

    def fetchall(self) -> list[dict[str, Any]]: ...


class ConnectionLike(Protocol):
    def cursor(self, *args: Any, **kwargs: Any) -> CursorLike: ...


def _row_to_job(row: dict[str, Any] | None) -> ProcessingJob | None:
    if row is None:
        return None
    return ProcessingJob(
        id=str(row["id"]),
        video_id=str(row["video_id"]),
        team_id=str(row["team_id"]),
        requested_by_user_id=row["requested_by_user_id"],
        status=JobStatus(row["status"]),
        external_job_id=row.get("external_job_id"),
        results_key=row.get("results_key"),
        error_message=row.get("error_message"),
        progress_percent=row.get("progress_percent"),
        artifacts=row.get("artifacts"),
        summary=row.get("summary"),
        our_team_side=row.get("our_team_side"),
        features=row.get("features"),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PostgresJobRepository:
    def __init__(self, *, connection: ConnectionLike) -> None:
        self._connection = connection

    def create_queued(
        self,
        *,
        job_id: str,
        video_id: str,
        team_id: str,
        requested_by_user_id: str,
        results_key: str,
    ) -> ProcessingJob:
        now = datetime.now(timezone.utc)
        with self._connection.cursor(row_factory=dict_row) as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO processing_jobs (
                        id, video_id, team_id, requested_by_user_id, status,
                        results_key, created_at, updated_at
                    ) VALUES (
                        %(job_id)s::uuid, %(video_id)s::uuid, %(team_id)s::uuid,
                        %(requested_by_user_id)s, %(status)s, %(results_key)s,
                        %(now)s, %(now)s
                    )
                    RETURNING *
                    """,
                    {
                        "job_id": job_id,
                        "video_id": video_id,
                        "team_id": team_id,
                        "requested_by_user_id": requested_by_user_id,
                        "status": JobStatus.QUEUED.value,
                        "results_key": results_key,
                        "now": now,
                    },
                )
            except psycopg.errors.UniqueViolation as exc:
                # The partial unique index on (video_id) WHERE status is active.
                # Normalized so the application layer never sees a DB exception.
                raise ActiveJobExistsError("Video already has an active job") from exc
            job = _row_to_job(cur.fetchone())
        assert job is not None  # INSERT ... RETURNING always yields a row
        return job

    def attach_external_id(self, *, job_id: str, external_job_id: str) -> ProcessingJob | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE processing_jobs
                   SET external_job_id = %(external_job_id)s,
                       updated_at = %(now)s
                 WHERE id = %(job_id)s::uuid
                RETURNING *
                """,
                {
                    "job_id": job_id,
                    "external_job_id": external_job_id,
                    "now": datetime.now(timezone.utc),
                },
            )
            return _row_to_job(cur.fetchone())

    def mark_failed(self, *, job_id: str, error_message: str) -> ProcessingJob | None:
        now = datetime.now(timezone.utc)
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE processing_jobs
                   SET status = %(status)s,
                       error_message = %(error_message)s,
                       finished_at = %(now)s,
                       updated_at = %(now)s
                 WHERE id = %(job_id)s::uuid
                RETURNING *
                """,
                {
                    "job_id": job_id,
                    "status": JobStatus.FAILED.value,
                    # Truncated: this can carry a provider error body, and the
                    # column is for humans debugging, not for storing payloads.
                    "error_message": error_message[:1000],
                    "now": now,
                },
            )
            return _row_to_job(cur.fetchone())

    def mark_running(self, *, job_id: str, progress_percent: int | None) -> ProcessingJob | None:
        now = datetime.now(timezone.utc)
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE processing_jobs
                   SET status = %(status)s,
                       progress_percent = COALESCE(%(progress_percent)s, progress_percent),
                       -- Preserved across repeated RUNNING callbacks so it means
                       -- "when work began", not "when we last heard from it".
                       started_at = COALESCE(started_at, %(now)s),
                       updated_at = %(now)s
                 WHERE id = %(job_id)s::uuid
                RETURNING *
                """,
                {
                    "job_id": job_id,
                    "status": JobStatus.RUNNING.value,
                    "progress_percent": progress_percent,
                    "now": now,
                },
            )
            return _row_to_job(cur.fetchone())

    def mark_done(
        self,
        *,
        job_id: str,
        results_key: str | None,
        artifacts: list[str] | None = None,
        summary: dict | None = None,
    ) -> ProcessingJob | None:
        now = datetime.now(timezone.utc)
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE processing_jobs
                   SET status = %(status)s,
                       results_key = COALESCE(%(results_key)s, results_key),
                       artifacts = COALESCE(%(artifacts)s::jsonb, artifacts),
                       summary = COALESCE(%(summary)s::jsonb, summary),
                       progress_percent = 100,
                       finished_at = %(now)s,
                       updated_at = %(now)s
                 WHERE id = %(job_id)s::uuid
                RETURNING *
                """,
                {
                    "job_id": job_id,
                    "status": JobStatus.DONE.value,
                    "results_key": results_key,
                    "artifacts": None if artifacts is None else json.dumps(artifacts),
                    "summary": None if summary is None else json.dumps(summary),
                    "now": now,
                },
            )
            return _row_to_job(cur.fetchone())

    def get_by_id_unscoped(self, *, job_id: str) -> ProcessingJob | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM processing_jobs WHERE id = %(job_id)s::uuid",
                {"job_id": job_id},
            )
            return _row_to_job(cur.fetchone())

    def get_by_id(self, *, job_id: str, team_id: str) -> ProcessingJob | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM processing_jobs
                 WHERE id = %(job_id)s::uuid AND team_id = %(team_id)s::uuid
                """,
                {"job_id": job_id, "team_id": team_id},
            )
            return _row_to_job(cur.fetchone())

    def set_our_team_side(self, *, job_id: str, team_id: str, our_team_side: int) -> ProcessingJob | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE processing_jobs
                   SET our_team_side = %(side)s, updated_at = NOW()
                 WHERE id = %(job_id)s::uuid AND team_id = %(team_id)s::uuid
                RETURNING *
                """,
                {"job_id": job_id, "team_id": team_id, "side": our_team_side},
            )
            return _row_to_job(cur.fetchone())

    def set_features(self, *, job_id: str, team_id: str, features: dict) -> ProcessingJob | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE processing_jobs
                   SET features = %(features)s::jsonb, updated_at = NOW()
                 WHERE id = %(job_id)s::uuid AND team_id = %(team_id)s::uuid
                RETURNING *
                """,
                {"job_id": job_id, "team_id": team_id, "features": json.dumps(features)},
            )
            return _row_to_job(cur.fetchone())

    def list_done_by_team(self, *, team_id: str) -> list[ProcessingJob]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM processing_jobs
                 WHERE team_id = %(team_id)s::uuid AND status = 'DONE'
                 ORDER BY created_at DESC
                """,
                {"team_id": team_id},
            )
            return [job for job in (_row_to_job(row) for row in cur.fetchall()) if job is not None]

    def list_by_video(self, *, video_id: str, team_id: str) -> list[ProcessingJob]:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM processing_jobs
                 WHERE video_id = %(video_id)s::uuid AND team_id = %(team_id)s::uuid
                 ORDER BY created_at DESC
                """,
                {"video_id": video_id, "team_id": team_id},
            )
            return [job for job in (_row_to_job(row) for row in cur.fetchall()) if job is not None]

    def find_active_for_video(self, *, video_id: str) -> ProcessingJob | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM processing_jobs
                 WHERE video_id = %(video_id)s::uuid
                   AND status IN ('QUEUED', 'RUNNING')
                 LIMIT 1
                """,
                {"video_id": video_id},
            )
            return _row_to_job(cur.fetchone())


class PostgresVideoLookup:
    """Read-only video access for the jobs module.

    Deliberately narrow rather than reusing the full video repository: jobs only
    need to know whether a video exists and is ready, and where its bytes live.
    """

    def __init__(self, *, connection: ConnectionLike) -> None:
        self._connection = connection

    def get_ready_video(self, *, video_id: str, team_id: str) -> tuple[str, str] | None:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, storage_key FROM videos
                 WHERE id = %(video_id)s::uuid
                   AND team_id = %(team_id)s::uuid
                   AND status = 'READY'
                   AND deleted_at IS NULL
                """,
                {"video_id": video_id, "team_id": team_id},
            )
            row = cur.fetchone()
            return None if row is None else (str(row["id"]), row["storage_key"])

    def exists(self, *, video_id: str, team_id: str) -> bool:
        with self._connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT 1 FROM videos
                 WHERE id = %(video_id)s::uuid
                   AND team_id = %(team_id)s::uuid
                   AND deleted_at IS NULL
                """,
                {"video_id": video_id, "team_id": team_id},
            )
            return cur.fetchone() is not None
