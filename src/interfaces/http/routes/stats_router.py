from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src.application.jobs.errors import JobError, job_error_http_status
from src.application.stats.use_cases import GetCourtPositionsUseCase, GetGameStatsUseCase


def create_stats_router(
    *,
    game_stats_use_case: GetGameStatsUseCase,
    court_positions_use_case: GetCourtPositionsUseCase,
) -> APIRouter:
    router = APIRouter(tags=["stats"])

    @router.get("/jobs/{job_id}/stats", response_model=None)
    def get_game_stats(job_id: UUID, team_id: UUID, request: Request):
        """Box score for a finished analysis.

        Team and per-player shooting totals, plus every shot with its court
        position and value. Everything is computed here, so the client renders it
        directly without interpreting analysis output.
        """

        try:
            return game_stats_use_case.execute(
                user_id=str(request.state.user_id),
                team_id=str(team_id),
                job_id=str(job_id),
            )
        except JobError as exc:
            return JSONResponse(status_code=job_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/jobs/{job_id}/court-positions", response_model=None)
    def get_court_positions(
        job_id: UUID,
        team_id: UUID,
        request: Request,
        sample_every: int = Query(
            1, ge=1, le=100,
            description="Keep one position in every N per player. Raise it for long videos.",
        ),
    ):
        """Where each tracked player was, in metres on a 28x15 court.

        One path per player rather than the pipeline's per-frame rows, which is
        what a court diagram or heatmap actually draws.
        """

        try:
            return court_positions_use_case.execute(
                user_id=str(request.state.user_id),
                team_id=str(team_id),
                job_id=str(job_id),
                sample_every=sample_every,
            )
        except JobError as exc:
            return JSONResponse(status_code=job_error_http_status(exc.code), content=exc.to_envelope())

    return router
