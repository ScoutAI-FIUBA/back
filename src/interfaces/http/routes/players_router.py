from __future__ import annotations

"""Players HTTP routes.

This router owns transport concerns (payload/path validation and status mapping)
and delegates business behavior to player application use cases.
"""

from datetime import date
from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.application.players.errors import PlayerError, player_error_http_status
from src.application.players.use_cases import (
    AssignPlayerTeamCommand,
    AssignPlayerTeamUseCase,
    CreatePlayerCommand,
    CreatePlayerUseCase,
    DeletePlayerCommand,
    DeletePlayerUseCase,
    ListPlayersByTeamUseCase,
    ListPlayersUseCase,
    UpdatePlayerCommand,
    UpdatePlayerUseCase,
)


class PlayerPayload(BaseModel):
    """Validated player payload used for create/update operations.

    Field bounds here are the HTTP contract; deeper business rules still execute in
    application use cases and may return ``PlayerError``.
    """

    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    birth_date: date
    height_cm: int = Field(gt=0, le=300)
    weight_kg: int = Field(gt=0, le=400)
    primary_position: str = Field(min_length=1, max_length=120)


def _to_player_response(player) -> dict[str, object]:
    """Serializes player entities to a stable JSON-facing shape."""

    return {
        "id": player.id,
        "first_name": player.first_name,
        "last_name": player.last_name,
        "birth_date": player.birth_date.isoformat(),
        "height_cm": player.height_cm,
        "weight_kg": player.weight_kg,
        "primary_position": player.primary_position,
        "team_id": player.team_id,
    }


def create_players_router(
    *,
    create_player_use_case: CreatePlayerUseCase,
    list_players_use_case: ListPlayersUseCase,
    list_players_by_team_use_case: ListPlayersByTeamUseCase,
    update_player_use_case: UpdatePlayerUseCase,
    delete_player_use_case: DeletePlayerUseCase,
    assign_player_team_use_case: AssignPlayerTeamUseCase,
) -> APIRouter:
    """Creates players HTTP endpoints and maps domain failures to HTTP responses.

    UUID path/query params are accepted as typed values at the HTTP boundary and
    converted to strings before invoking use cases.
    """

    router = APIRouter(prefix="/players", tags=["players"])

    @router.post("", status_code=HTTPStatus.CREATED, response_model=None)
    def create_player(payload: PlayerPayload, request: Request):
        """Creates one player from validated payload fields."""

        try:
            player = create_player_use_case.execute(
                CreatePlayerCommand(
                    user_id=str(request.state.user_id),
                    first_name=payload.first_name,
                    last_name=payload.last_name,
                    birth_date=payload.birth_date,
                    height_cm=payload.height_cm,
                    weight_kg=payload.weight_kg,
                    primary_position=payload.primary_position,
                )
            )
            return {"player": _to_player_response(player)}
        except PlayerError as exc:
            return JSONResponse(status_code=player_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("", response_model=None)
    def list_players(request: Request, team_id: UUID | None = None):
        """Lists the scout's players, optionally filtered to one of their teams."""

        user_id = str(request.state.user_id)
        if team_id is None:
            players = list_players_use_case.execute(user_id=user_id)
        else:
            players = list_players_by_team_use_case.execute(user_id=user_id, team_id=str(team_id))
        return {"players": [_to_player_response(player) for player in players]}

    @router.put("/{player_id}", response_model=None)
    def update_player(player_id: UUID, payload: PlayerPayload, request: Request):
        """Updates one player and maps application errors to HTTP envelopes."""

        try:
            player = update_player_use_case.execute(
                UpdatePlayerCommand(
                    user_id=str(request.state.user_id),
                    id=str(player_id),
                    first_name=payload.first_name,
                    last_name=payload.last_name,
                    birth_date=payload.birth_date,
                    height_cm=payload.height_cm,
                    weight_kg=payload.weight_kg,
                    primary_position=payload.primary_position,
                )
            )
            return {"player": _to_player_response(player)}
        except PlayerError as exc:
            return JSONResponse(status_code=player_error_http_status(exc.code), content=exc.to_envelope())

    @router.delete("/{player_id}", response_model=None)
    def delete_player(player_id: UUID, request: Request):
        """Deletes one player and returns HTTP 204 on success."""

        try:
            delete_player_use_case.execute(
                DeletePlayerCommand(user_id=str(request.state.user_id), id=str(player_id))
            )
            return Response(status_code=HTTPStatus.NO_CONTENT)
        except PlayerError as exc:
            return JSONResponse(status_code=player_error_http_status(exc.code), content=exc.to_envelope())

    @router.put("/{player_id}/team/{team_id}", response_model=None)
    def assign_player_to_team(player_id: UUID, team_id: UUID, request: Request):
        """Assigns a player to a team using typed UUID boundary inputs."""

        try:
            player = assign_player_team_use_case.execute(
                AssignPlayerTeamCommand(
                    user_id=str(request.state.user_id),
                    player_id=str(player_id),
                    team_id=str(team_id),
                )
            )
            return {"player": _to_player_response(player)}
        except PlayerError as exc:
            return JSONResponse(status_code=player_error_http_status(exc.code), content=exc.to_envelope())

    return router
