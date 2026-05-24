from __future__ import annotations

from datetime import date
from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.application.players.errors import PlayerError, player_error_http_status
from src.application.players.use_cases import (
    CreatePlayerCommand,
    CreatePlayerUseCase,
    DeletePlayerCommand,
    DeletePlayerUseCase,
    ListPlayersUseCase,
    UpdatePlayerCommand,
    UpdatePlayerUseCase,
)


class PlayerPayload(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    birth_date: date
    height_cm: int = Field(gt=0, le=300)
    weight_kg: int = Field(gt=0, le=400)
    primary_position: str = Field(min_length=1, max_length=120)


def _to_player_response(player) -> dict[str, object]:
    return {
        "id": player.id,
        "first_name": player.first_name,
        "last_name": player.last_name,
        "birth_date": player.birth_date.isoformat(),
        "height_cm": player.height_cm,
        "weight_kg": player.weight_kg,
        "primary_position": player.primary_position,
    }


def create_players_router(
    *,
    create_player_use_case: CreatePlayerUseCase,
    list_players_use_case: ListPlayersUseCase,
    update_player_use_case: UpdatePlayerUseCase,
    delete_player_use_case: DeletePlayerUseCase,
) -> APIRouter:
    router = APIRouter(prefix="/players", tags=["players"])

    @router.post("", status_code=HTTPStatus.CREATED, response_model=None)
    def create_player(payload: PlayerPayload):
        try:
            player = create_player_use_case.execute(
                CreatePlayerCommand(
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
    def list_players():
        players = list_players_use_case.execute()
        return {"players": [_to_player_response(player) for player in players]}

    @router.put("/{player_id}", response_model=None)
    def update_player(player_id: UUID, payload: PlayerPayload):
        try:
            player = update_player_use_case.execute(
                UpdatePlayerCommand(
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
    def delete_player(player_id: UUID):
        try:
            delete_player_use_case.execute(DeletePlayerCommand(id=str(player_id)))
            return Response(status_code=HTTPStatus.NO_CONTENT)
        except PlayerError as exc:
            return JSONResponse(status_code=player_error_http_status(exc.code), content=exc.to_envelope())

    return router
