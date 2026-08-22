from __future__ import annotations

from datetime import date
from http import HTTPStatus
from typing import Any, Annotated
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints, field_validator

from src.application.matches.errors import MatchError, match_error_http_status
from src.application.matches.use_cases import (
    CreateMatchCommand,
    CreateMatchUseCase,
    GetMatchStatsUseCase,
    GetMatchUseCase,
    ListMatchesUseCase,
    ReplaceMatchParticipantInput,
    ReplaceMatchStatsCommand,
    ReplaceMatchStatsUseCase,
)


JerseyNumber = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,2}$")]


class CreateMatchPayload(BaseModel):
    home_team_id: UUID
    away_team_id: UUID
    match_date: date
    description: str | None = Field(default=None, max_length=2000)


class MatchParticipantPayload(BaseModel):
    team_side: Annotated[str, StringConstraints(pattern=r"^(HOME|AWAY)$")]
    display_name: str = Field(min_length=1, max_length=200)
    player_id: UUID | None = None
    jersey_number: JerseyNumber | None = None

    @field_validator("jersey_number", mode="before")
    @classmethod
    def _blank_means_none(cls, value: object) -> object:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class ReplaceMatchStatsPayload(BaseModel):
    stats: Any | None = None
    winner_team_id: UUID | None = None
    participants: list[MatchParticipantPayload] = Field(default_factory=list)


def _to_match_payload(match) -> dict[str, object]:
    return {
        "id": match.id,
        "home_team_id": match.home_team_id,
        "away_team_id": match.away_team_id,
        "winner_team_id": match.winner_team_id,
        "match_date": match.match_date.isoformat(),
        "description": match.description,
        "stats": match.stats,
        "created_at": match.created_at.isoformat() if match.created_at else None,
        "updated_at": match.updated_at.isoformat() if match.updated_at else None,
    }


def _to_participant_payload(participant) -> dict[str, object]:
    return {
        "id": participant.id,
        "match_id": participant.match_id,
        "player_id": participant.player_id,
        "team_side": participant.team_side,
        "display_name": participant.display_name,
        "jersey_number": participant.jersey_number,
    }


def create_matches_router(
    *,
    create_match_use_case: CreateMatchUseCase,
    list_matches_use_case: ListMatchesUseCase,
    get_match_use_case: GetMatchUseCase,
    replace_match_stats_use_case: ReplaceMatchStatsUseCase,
    get_match_stats_use_case: GetMatchStatsUseCase,
) -> APIRouter:
    router = APIRouter(prefix="/matches", tags=["matches"])

    @router.post("", status_code=HTTPStatus.CREATED, response_model=None)
    def create_match(payload: CreateMatchPayload, request: Request):
        try:
            match = create_match_use_case.execute(
                CreateMatchCommand(
                    user_id=str(request.state.user_id),
                    home_team_id=str(payload.home_team_id),
                    away_team_id=str(payload.away_team_id),
                    match_date=payload.match_date,
                    description=payload.description,
                )
            )
            return {"match": _to_match_payload(match)}
        except MatchError as exc:
            return JSONResponse(status_code=match_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("", response_model=None)
    def list_matches(request: Request, team_id: UUID | None = None):
        try:
            matches = list_matches_use_case.execute(
                user_id=str(request.state.user_id),
                team_id=str(team_id) if team_id is not None else None,
            )
            return {"matches": [_to_match_payload(match) for match in matches]}
        except MatchError as exc:
            return JSONResponse(status_code=match_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/{match_id}", response_model=None)
    def get_match(match_id: UUID, request: Request):
        try:
            match = get_match_use_case.execute(user_id=str(request.state.user_id), match_id=str(match_id))
            return {"match": _to_match_payload(match)}
        except MatchError as exc:
            return JSONResponse(status_code=match_error_http_status(exc.code), content=exc.to_envelope())

    @router.put("/{match_id}/stats", response_model=None)
    def replace_match_stats(match_id: UUID, payload: ReplaceMatchStatsPayload, request: Request):
        try:
            view = replace_match_stats_use_case.execute(
                ReplaceMatchStatsCommand(
                    user_id=str(request.state.user_id),
                    match_id=str(match_id),
                    stats=payload.stats,
                    winner_team_id=str(payload.winner_team_id) if payload.winner_team_id is not None else None,
                    participants=[
                        ReplaceMatchParticipantInput(
                            team_side=participant.team_side,
                            display_name=participant.display_name,
                            player_id=str(participant.player_id) if participant.player_id is not None else None,
                            jersey_number=participant.jersey_number,
                        )
                        for participant in payload.participants
                    ],
                )
            )
            return {
                "match": _to_match_payload(view.match),
                "participants": [_to_participant_payload(participant) for participant in view.participants],
            }
        except MatchError as exc:
            return JSONResponse(status_code=match_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/{match_id}/stats", response_model=None)
    def get_match_stats(match_id: UUID, request: Request):
        try:
            view = get_match_stats_use_case.execute(user_id=str(request.state.user_id), match_id=str(match_id))
            return {
                "match": _to_match_payload(view.match),
                "participants": [_to_participant_payload(participant) for participant in view.participants],
            }
        except MatchError as exc:
            return JSONResponse(status_code=match_error_http_status(exc.code), content=exc.to_envelope())

    return router
