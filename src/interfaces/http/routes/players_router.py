from __future__ import annotations

"""Players HTTP routes.

This router owns transport concerns (payload/path validation and status mapping)
and delegates business behavior to player application use cases.
"""

from datetime import date
from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints, field_validator

from src.application.players.errors import PlayerError, player_error_http_status
from src.application.stats.player_analysis import (
    GetPlayerAnalysisStatsUseCase,
    GetPlayerShotChartUseCase,
    ResyncTeamAnalysesUseCase,
)
from src.application.matches.errors import MatchError, match_error_http_status
from src.application.matches.use_cases import GetPlayerMatchesUseCase
from src.application.players.use_cases import (
    AssignPlayerTeamCommand,
    AssignPlayerTeamUseCase,
    CreatePlayerCommand,
    CreatePlayerUseCase,
    DeletePlayerCommand,
    DeletePlayerUseCase,
    GetPlayerStatsUseCase,
    ListPlayersByTeamUseCase,
    ListPlayersUseCase,
    UpdatePlayerCommand,
    UpdatePlayerUseCase,
)
from src.interfaces.http.schemas.player_analysis import AnalysisStatsResponse, ShotChartResponse


JerseyNumber = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,2}$")]


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
    jersey_number: JerseyNumber | None = None

    @field_validator("jersey_number", mode="before")
    @classmethod
    def _blank_jersey_number_means_unassigned(cls, value: object) -> object:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


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
        "jersey_number": player.jersey_number,
        "team_id": player.team_id,
    }


def _to_player_match_response(match) -> dict[str, object]:
    return {
        "id": match.id,
        "home_team_id": match.home_team_id,
        "away_team_id": match.away_team_id,
        "winner_team_id": match.winner_team_id,
        "match_date": match.match_date.isoformat(),
        "description": match.description,
        "stats": match.stats,
    }


def create_players_router(
    *,
    create_player_use_case: CreatePlayerUseCase,
    list_players_use_case: ListPlayersUseCase,
    list_players_by_team_use_case: ListPlayersByTeamUseCase,
    update_player_use_case: UpdatePlayerUseCase,
    delete_player_use_case: DeletePlayerUseCase,
    assign_player_team_use_case: AssignPlayerTeamUseCase,
    get_player_stats_use_case: GetPlayerStatsUseCase,
    get_player_matches_use_case: GetPlayerMatchesUseCase,
    get_player_shot_chart_use_case: GetPlayerShotChartUseCase | None = None,
    get_player_analysis_stats_use_case: GetPlayerAnalysisStatsUseCase | None = None,
    resync_team: ResyncTeamAnalysesUseCase | None = None,
) -> APIRouter:
    """Creates players HTTP endpoints and maps domain failures to HTTP responses.

    UUID path/query params are accepted as typed values at the HTTP boundary and
    converted to strings before invoking use cases.
    """

    router = APIRouter(prefix="/players", tags=["players"])

    def _team_of(user_id: str, player_id: str) -> str | None:
        """The player's team before a change, read only when a re-sync will need it."""

        if resync_team is None:
            return None
        try:
            return get_player_stats_use_case.execute(user_id=user_id, player_id=player_id).team_id
        except Exception:  # noqa: BLE001 - the re-sync is best effort and must not affect the request
            return None

    def _resync(background_tasks: BackgroundTasks, *team_ids: str | None) -> None:
        """Re-sync these teams' latest analyses after the response is sent (who a track links to
        depends on the roster)."""

        if resync_team is None:
            return
        for team_id in dict.fromkeys(team_id for team_id in team_ids if team_id):
            background_tasks.add_task(resync_team.execute, team_id)

    @router.post("", status_code=HTTPStatus.CREATED, response_model=None)
    def create_player(payload: PlayerPayload, request: Request, background_tasks: BackgroundTasks):
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
                    jersey_number=payload.jersey_number,
                )
            )
            _resync(background_tasks, player.team_id)
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
    def update_player(player_id: UUID, payload: PlayerPayload, request: Request, background_tasks: BackgroundTasks):
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
                    jersey_number=payload.jersey_number,
                )
            )
            _resync(background_tasks, player.team_id)
            return {"player": _to_player_response(player)}
        except PlayerError as exc:
            return JSONResponse(status_code=player_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/{player_id}/stats", response_model=None)
    def get_player_stats(player_id: UUID, request: Request):
        try:
            player = get_player_stats_use_case.execute(user_id=str(request.state.user_id), player_id=str(player_id))
            return {"player": {"id": player.id, "stats": player.stats}}
        except PlayerError as exc:
            return JSONResponse(status_code=player_error_http_status(exc.code), content=exc.to_envelope())

    if get_player_shot_chart_use_case is not None:

        @router.get("/{player_id}/shot-chart", response_model=ShotChartResponse)
        def get_player_shot_chart(player_id: UUID, request: Request):
            """Every shot the player took across their analysed videos, with court positions.

            Each shot has `x_m`/`y_m` on the court frame in `court`, `made` and a `result` of
            made / missed / unknown (green, red, neither), plus the video it came from.
            `shot_key` is unique among the player's shots. `shot_value` is worth by location
            even when missed; `timestamp_seconds` counts from the start of the video.
            """

            try:
                return get_player_shot_chart_use_case.execute(
                    user_id=str(request.state.user_id), player_id=str(player_id)
                )
            except PlayerError as exc:
                return JSONResponse(status_code=player_error_http_status(exc.code), content=exc.to_envelope())

    if get_player_analysis_stats_use_case is not None:

        @router.get("/{player_id}/analysis-stats", response_model=AnalysisStatsResponse)
        def get_player_analysis_stats(player_id: UUID, request: Request):
            """Totals the video analyses measured for the player, across all their videos.

            Shooting `pct` values are fractions 0..1 (null without attempts); the integer
            percent 0..100 contract belongs to `players.stats` (`GET /players/{id}/stats`).
            `seconds_on_screen` is time visible in the videos, not minutes played.
            """

            try:
                return get_player_analysis_stats_use_case.execute(
                    user_id=str(request.state.user_id), player_id=str(player_id)
                )
            except PlayerError as exc:
                return JSONResponse(status_code=player_error_http_status(exc.code), content=exc.to_envelope())

    @router.get("/{player_id}/matches", response_model=None)
    def get_player_matches(player_id: UUID, request: Request):
        try:
            matches = get_player_matches_use_case.execute(user_id=str(request.state.user_id), player_id=str(player_id))
            return {"matches": [_to_player_match_response(match) for match in matches]}
        except MatchError as exc:
            return JSONResponse(status_code=match_error_http_status(exc.code), content=exc.to_envelope())

    @router.delete("/{player_id}", response_model=None)
    def delete_player(player_id: UUID, request: Request, background_tasks: BackgroundTasks):
        """Deletes one player and returns HTTP 204 on success."""

        team_before = _team_of(str(request.state.user_id), str(player_id))
        try:
            delete_player_use_case.execute(
                DeletePlayerCommand(user_id=str(request.state.user_id), id=str(player_id))
            )
            _resync(background_tasks, team_before)
            return Response(status_code=HTTPStatus.NO_CONTENT)
        except PlayerError as exc:
            return JSONResponse(status_code=player_error_http_status(exc.code), content=exc.to_envelope())

    @router.put("/{player_id}/team/{team_id}", response_model=None)
    def assign_player_to_team(player_id: UUID, team_id: UUID, request: Request, background_tasks: BackgroundTasks):
        """Assigns a player to a team using typed UUID boundary inputs."""

        previous_team = _team_of(str(request.state.user_id), str(player_id))
        try:
            player = assign_player_team_use_case.execute(
                AssignPlayerTeamCommand(
                    user_id=str(request.state.user_id),
                    player_id=str(player_id),
                    team_id=str(team_id),
                )
            )
            _resync(background_tasks, previous_team, player.team_id)
            return {"player": _to_player_response(player)}
        except PlayerError as exc:
            return JSONResponse(status_code=player_error_http_status(exc.code), content=exc.to_envelope())

    return router
