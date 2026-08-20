from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.application.players.errors import (
    INVALID_POSITION,
    PLAYER_NOT_FOUND,
    TEAM_NOT_FOUND,
    PlayerError,
)
from src.application.players.ports import IdGeneratorPort, PlayerRepositoryPort, UnitOfWorkPort
from src.application.team.ports import TeamRepositoryPort
from src.domain.players.entities import Player
from src.domain.players.positions import VALID_POSITION_CODES, is_valid_position


def _validate_position(code: str) -> None:
    if not is_valid_position(code):
        raise PlayerError(
            code=INVALID_POSITION,
            message=f"Invalid position {code!r}.",
            details={"allowed": sorted(VALID_POSITION_CODES)},
        )


@dataclass(frozen=True)
class CreatePlayerCommand:
    user_id: str
    first_name: str
    last_name: str
    birth_date: date
    height_cm: int
    weight_kg: int
    primary_position: str


@dataclass(frozen=True)
class UpdatePlayerCommand:
    user_id: str
    id: str
    first_name: str
    last_name: str
    birth_date: date
    height_cm: int
    weight_kg: int
    primary_position: str


@dataclass(frozen=True)
class DeletePlayerCommand:
    user_id: str
    id: str


@dataclass(frozen=True)
class AssignPlayerTeamCommand:
    user_id: str
    player_id: str
    team_id: str


class CreatePlayerUseCase:
    def __init__(self, *, players: PlayerRepositoryPort, ids: IdGeneratorPort, uow: UnitOfWorkPort) -> None:
        self._players = players
        self._ids = ids
        self._uow = uow

    def execute(self, command: CreatePlayerCommand) -> Player:
        _validate_position(command.primary_position)
        player = Player(
            id=self._ids.new_id(),
            first_name=command.first_name,
            last_name=command.last_name,
            birth_date=command.birth_date,
            height_cm=command.height_cm,
            weight_kg=command.weight_kg,
            primary_position=command.primary_position,
            owner_user_id=command.user_id,
            team_id=None,
        )
        with self._uow.transaction():
            return self._players.create(player)


class ListPlayersUseCase:
    def __init__(self, *, players: PlayerRepositoryPort) -> None:
        self._players = players

    def execute(self, *, user_id: str) -> list[Player]:
        return self._players.list_by_owner(owner_user_id=user_id)


class ListPlayersByTeamUseCase:
    def __init__(self, *, players: PlayerRepositoryPort) -> None:
        self._players = players

    def execute(self, *, user_id: str, team_id: str) -> list[Player]:
        return self._players.list_by_owner_and_team(owner_user_id=user_id, team_id=team_id)


class UpdatePlayerUseCase:
    def __init__(self, *, players: PlayerRepositoryPort, uow: UnitOfWorkPort) -> None:
        self._players = players
        self._uow = uow

    def execute(self, command: UpdatePlayerCommand) -> Player:
        _validate_position(command.primary_position)
        with self._uow.transaction():
            updated = self._players.update(
                player_id=command.id,
                owner_user_id=command.user_id,
                first_name=command.first_name,
                last_name=command.last_name,
                birth_date=command.birth_date,
                height_cm=command.height_cm,
                weight_kg=command.weight_kg,
                primary_position=command.primary_position,
            )
        if updated is None:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")
        return updated


class DeletePlayerUseCase:
    def __init__(self, *, players: PlayerRepositoryPort, uow: UnitOfWorkPort) -> None:
        self._players = players
        self._uow = uow

    def execute(self, command: DeletePlayerCommand) -> None:
        with self._uow.transaction():
            deleted = self._players.delete(command.id, owner_user_id=command.user_id)
        if not deleted:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")


class AssignPlayerTeamUseCase:
    def __init__(self, *, players: PlayerRepositoryPort, teams: TeamRepositoryPort, uow: UnitOfWorkPort) -> None:
        self._players = players
        self._teams = teams
        self._uow = uow

    def execute(self, command: AssignPlayerTeamCommand) -> Player:
        with self._uow.transaction():
            if not self._teams.is_owned_by(team_id=command.team_id, owner_user_id=command.user_id):
                raise PlayerError(code=TEAM_NOT_FOUND, message="Team not found")
            player = self._players.assign_team(
                player_id=command.player_id,
                owner_user_id=command.user_id,
                team_id=command.team_id,
            )
        if player is None:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")
        return player
