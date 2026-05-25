from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.application.players.errors import PLAYER_NOT_FOUND, TEAM_NOT_FOUND, PlayerError
from src.application.players.ports import IdGeneratorPort, PlayerRepositoryPort, UnitOfWorkPort
from src.application.team.ports import TeamRepositoryPort
from src.domain.players.entities import Player


@dataclass(frozen=True)
class CreatePlayerCommand:
    first_name: str
    last_name: str
    birth_date: date
    height_cm: int
    weight_kg: int
    primary_position: str


@dataclass(frozen=True)
class UpdatePlayerCommand:
    id: str
    first_name: str
    last_name: str
    birth_date: date
    height_cm: int
    weight_kg: int
    primary_position: str


@dataclass(frozen=True)
class DeletePlayerCommand:
    id: str


@dataclass(frozen=True)
class AssignPlayerTeamCommand:
    player_id: str
    team_id: str


class CreatePlayerUseCase:
    def __init__(self, *, players: PlayerRepositoryPort, ids: IdGeneratorPort, uow: UnitOfWorkPort) -> None:
        self._players = players
        self._ids = ids
        self._uow = uow

    def execute(self, command: CreatePlayerCommand) -> Player:
        player = Player(
            id=self._ids.new_id(),
            first_name=command.first_name,
            last_name=command.last_name,
            birth_date=command.birth_date,
            height_cm=command.height_cm,
            weight_kg=command.weight_kg,
            primary_position=command.primary_position,
            team_id=None,
        )
        with self._uow.transaction():
            return self._players.create(player)


class ListPlayersUseCase:
    def __init__(self, *, players: PlayerRepositoryPort) -> None:
        self._players = players

    def execute(self) -> list[Player]:
        return self._players.list_all()


class ListPlayersByTeamUseCase:
    def __init__(self, *, players: PlayerRepositoryPort) -> None:
        self._players = players

    def execute(self, team_id: str) -> list[Player]:
        return self._players.list_by_team(team_id)


class UpdatePlayerUseCase:
    def __init__(self, *, players: PlayerRepositoryPort, uow: UnitOfWorkPort) -> None:
        self._players = players
        self._uow = uow

    def execute(self, command: UpdatePlayerCommand) -> Player:
        with self._uow.transaction():
            updated = self._players.update(
                player_id=command.id,
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
            deleted = self._players.delete(command.id)
        if not deleted:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")


class AssignPlayerTeamUseCase:
    def __init__(self, *, players: PlayerRepositoryPort, teams: TeamRepositoryPort, uow: UnitOfWorkPort) -> None:
        self._players = players
        self._teams = teams
        self._uow = uow

    def execute(self, command: AssignPlayerTeamCommand) -> Player:
        with self._uow.transaction():
            if not self._teams.exists(command.team_id):
                raise PlayerError(code=TEAM_NOT_FOUND, message="Team not found")
            player = self._players.assign_team(player_id=command.player_id, team_id=command.team_id)
        if player is None:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")
        return player
