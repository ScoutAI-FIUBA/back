from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.application.matches.errors import MatchError, match_error_http_status
from src.application.matches.use_cases import GetTeamStatsUseCase
from src.application.team.errors import TeamError, team_error_http_status
from src.application.team.use_cases import (
    CreateTeamCommand,
    CreateTeamUseCase,
    DeleteTeamCommand,
    DeleteTeamUseCase,
    ListTeamsUseCase,
    UpdateTeamCommand,
    UpdateTeamUseCase,
)


class CreateTeamRequest(BaseModel):
    """Request body contract for team creation."""

    name: str = Field(min_length=1)
    short_name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    country: str = Field(min_length=1)
    is_own: bool = False


class UpdateTeamRequest(BaseModel):
    """Request body contract for team updates."""

    name: str = Field(min_length=1)
    short_name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    country: str = Field(min_length=1)
    # Omitted or null keeps the stored value, so stale clients cannot reset it.
    is_own: bool | None = None


def _to_payload(team) -> dict[str, object]:
    """Converts team entities into the route response payload shape."""

    return {
        "id": team.id,
        "name": team.name,
        "short_name": team.short_name,
        "city": team.city,
        "country": team.country,
        "created_at": team.created_at.isoformat(),
        "is_own": team.is_own,
    }


def create_team_router(
    *,
    create_team_use_case: CreateTeamUseCase,
    list_teams_use_case: ListTeamsUseCase,
    update_team_use_case: UpdateTeamUseCase,
    delete_team_use_case: DeleteTeamUseCase,
    get_team_stats_use_case: GetTeamStatsUseCase,
) -> APIRouter:
    """Creates team endpoints and defines HTTP-level not-found semantics.

    Use cases may return ``None``/``False`` for missing teams; this boundary maps
    those outcomes to ``404 Team not found`` for API consistency.
    """

    router = APIRouter(prefix="/teams", tags=["teams"])

    @router.post("", response_model=None, status_code=HTTPStatus.CREATED)
    def create_team(payload: CreateTeamRequest, request: Request):
        team = create_team_use_case.execute(
            CreateTeamCommand(
                user_id=str(request.state.user_id),
                name=payload.name,
                short_name=payload.short_name,
                city=payload.city,
                country=payload.country,
                is_own=payload.is_own,
            )
        )
        return {"team": _to_payload(team)}

    @router.get("", response_model=None)
    def list_teams(request: Request):
        teams = list_teams_use_case.execute(user_id=str(request.state.user_id))
        return {"teams": [_to_payload(team) for team in teams]}

    @router.put("/{team_id}", response_model=None)
    def update_team(team_id: UUID, payload: UpdateTeamRequest, request: Request):
        team = update_team_use_case.execute(
            UpdateTeamCommand(
                user_id=str(request.state.user_id),
                team_id=str(team_id),
                name=payload.name,
                short_name=payload.short_name,
                city=payload.city,
                country=payload.country,
                is_own=payload.is_own,
            )
        )
        if team is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Team not found")
        return {"team": _to_payload(team)}

    @router.delete("/{team_id}", response_model=None, status_code=HTTPStatus.NO_CONTENT)
    def delete_team(team_id: UUID, request: Request):
        try:
            deleted = delete_team_use_case.execute(
                DeleteTeamCommand(user_id=str(request.state.user_id), team_id=str(team_id))
            )
            if not deleted:
                raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Team not found")
            return Response(status_code=HTTPStatus.NO_CONTENT)
        except TeamError as exc:
            return JSONResponse(status_code=team_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/{team_id}/stats", response_model=None)
    def get_team_stats(team_id: UUID, request: Request):
        try:
            summary = get_team_stats_use_case.execute(user_id=str(request.state.user_id), team_id=str(team_id))
            return {
                "team": {
                    "id": summary.team_id,
                    "matches_played": summary.matches_played,
                    "wins": summary.wins,
                    "losses": summary.losses,
                    "results": [
                        {
                            "match_id": result.match_id,
                            "match_date": result.match_date.isoformat(),
                            "home_team_id": result.home_team_id,
                            "away_team_id": result.away_team_id,
                            "winner_team_id": result.winner_team_id,
                            "description": result.description,
                            "result": result.result,
                        }
                        for result in summary.results
                    ],
                }
            }
        except MatchError as exc:
            return JSONResponse(status_code=match_error_http_status(exc.code), content=exc.to_envelope())

    return router
