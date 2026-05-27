from __future__ import annotations

import logging

from collections.abc import Callable

from fastapi import FastAPI, HTTPException
import psycopg

from src.application.use_cases import GetHealthStatus
from src.infrastructure.health_adapter import InMemoryHealthAdapter

logger = logging.getLogger(__name__)


def register_health_routes(
    app: FastAPI,
    *,
    database_url: str,
    db_health_connect_timeout: int,
    connect: Callable[..., psycopg.Connection] = psycopg.connect,
) -> None:
    """Registers liveness/readiness-style endpoints for the HTTP service.

    ``connect`` is injectable to keep DB health checks testable without touching
    global driver state.
    """

    @app.get("/health")
    def health() -> dict[str, str]:
        """Returns in-memory service health independent from database availability."""

        use_case = GetHealthStatus(InMemoryHealthAdapter())
        status = use_case.execute()
        return {"status": status.status}

    @app.get("/db-health")
    def db_health() -> dict[str, str]:
        """Probes database connectivity and returns 503 when unavailable."""

        try:
            with connect(
                database_url,
                connect_timeout=db_health_connect_timeout,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            return {"status": "ok"}
        except Exception as exc:
            logger.warning(
                "Database health check failed (%s)",
                type(exc).__name__,
            )
            raise HTTPException(status_code=503, detail="Database unavailable")
