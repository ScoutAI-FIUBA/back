from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src.application.jobs.errors import JobError, job_error_http_status
from src.application.stats.use_cases import (
    GetCourtPositionsUseCase,
    GetGameStatsUseCase,
    GetShotChartUseCase,
    GetSimilarClipsUseCase,
    GetTeamSidesUseCase,
)


def create_stats_router(
    *,
    game_stats_use_case: GetGameStatsUseCase,
    court_positions_use_case: GetCourtPositionsUseCase,
    shot_chart_use_case: GetShotChartUseCase,
    team_sides_use_case: GetTeamSidesUseCase,
    similar_clips_use_case: GetSimilarClipsUseCase,
) -> APIRouter:
    router = APIRouter(tags=["stats"])

    @router.get("/jobs/{job_id}/similar", response_model=None)
    def get_similar_clips(
        job_id: UUID,
        team_id: UUID,
        request: Request,
        limit: int = Query(5, ge=1, le=50, description="How many similar clips to return."),
        movement_weight: float = Query(
            0.5, ge=0.0, le=1.0,
            description="0 = compare by shots only, 1 = by movement only, 0.5 = even.",
        ),
    ):
        """Other finished clips ranked by how similar their play is to this one.

        Compared on shot locations and how players moved on court — never player
        identity. `movement_weight` slides between the two signals. Each result
        carries the overall `score` plus the `shot_score` / `movement_score` that
        produced it.
        """

        try:
            return similar_clips_use_case.execute(
                user_id=str(request.state.user_id),
                team_id=str(team_id),
                job_id=str(job_id),
                limit=limit,
                movement_weight=movement_weight,
            )
        except JobError as exc:
            return JSONResponse(status_code=job_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/jobs/{job_id}/team-sides", response_model=None)
    def get_team_sides(job_id: UUID, team_id: UUID, request: Request):
        """The two pipeline sides, with a suggestion of which one is our team.

        The pipeline splits players into side 0 and side 1 without knowing which
        is which; this compares the numbers it read against our roster so the UI
        can pre-select the likely side. Confirm it with PUT /jobs/{id}/our-team.
        """

        try:
            return team_sides_use_case.execute(
                user_id=str(request.state.user_id),
                team_id=str(team_id),
                job_id=str(job_id),
            )
        except JobError as exc:
            return JSONResponse(status_code=job_error_http_status(exc.code), content=exc.to_envelope())

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

    @router.get("/jobs/{job_id}/shot-chart", response_model=None)
    def get_shot_chart(
        job_id: UUID,
        team_id: UUID,
        request: Request,
        track_id: int | None = Query(
            None, description="Limit the chart to one tracked player. Omit for every shot.",
        ),
    ):
        """Every located shot as a court marker, for drawing a shot chart.

        Each marker carries its court position and whether it went in (made vs
        missed), and the response includes the court geometry needed to draw the
        floor and three-point line. Pass `track_id` for a single player's chart.
        """

        try:
            return shot_chart_use_case.execute(
                user_id=str(request.state.user_id),
                team_id=str(team_id),
                job_id=str(job_id),
                track_id=track_id,
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
