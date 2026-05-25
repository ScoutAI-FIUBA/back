from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

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
    name: str = Field(min_length=1)
    short_name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    country: str = Field(min_length=1)


class UpdateTeamRequest(BaseModel):
    name: str = Field(min_length=1)
    short_name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    country: str = Field(min_length=1)


def _to_payload(team) -> dict[str, str]:
    return {
        "id": team.id,
        "name": team.name,
        "short_name": team.short_name,
        "city": team.city,
        "country": team.country,
        "created_at": team.created_at.isoformat(),
    }


def create_team_router(
    *,
    create_team_use_case: CreateTeamUseCase,
    list_teams_use_case: ListTeamsUseCase,
    update_team_use_case: UpdateTeamUseCase,
    delete_team_use_case: DeleteTeamUseCase,
) -> APIRouter:
    router = APIRouter(prefix="/teams", tags=["teams"])

    @router.post("", response_model=None, status_code=HTTPStatus.CREATED)
    def create_team(payload: CreateTeamRequest):
        team = create_team_use_case.execute(
            CreateTeamCommand(
                name=payload.name,
                short_name=payload.short_name,
                city=payload.city,
                country=payload.country,
            )
        )
        return {"team": _to_payload(team)}

    @router.get("", response_model=None)
    def list_teams():
        teams = list_teams_use_case.execute()
        return {"teams": [_to_payload(team) for team in teams]}

    @router.put("/{team_id}", response_model=None)
    def update_team(team_id: UUID, payload: UpdateTeamRequest):
        team = update_team_use_case.execute(
            UpdateTeamCommand(
                team_id=str(team_id),
                name=payload.name,
                short_name=payload.short_name,
                city=payload.city,
                country=payload.country,
            )
        )
        if team is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Team not found")
        return {"team": _to_payload(team)}

    @router.delete("/{team_id}", response_model=None, status_code=HTTPStatus.NO_CONTENT)
    def delete_team(team_id: UUID):
        deleted = delete_team_use_case.execute(DeleteTeamCommand(team_id=str(team_id)))
        if not deleted:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Team not found")
        return Response(status_code=HTTPStatus.NO_CONTENT)

    return router
