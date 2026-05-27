from __future__ import annotations

"""Player application use cases.

This module coordinates player-related workflows and keeps persistence details
behind repository and unit-of-work ports.
"""

from dataclasses import dataclass
from datetime import date

from src.application.players.errors import PLAYER_NOT_FOUND, TEAM_NOT_FOUND, PlayerError
from src.application.players.ports import IdGeneratorPort, PlayerRepositoryPort, UnitOfWorkPort
from src.application.team.ports import TeamRepositoryPort
from src.domain.players.entities import Player


@dataclass(frozen=True)
class CreatePlayerCommand:
    """Input contract for creating a player aggregate."""

    first_name: str
    last_name: str
    birth_date: date
    height_cm: int
    weight_kg: int
    primary_position: str


@dataclass(frozen=True)
class UpdatePlayerCommand:
    """Input contract for full player profile updates."""

    id: str
    first_name: str
    last_name: str
    birth_date: date
    height_cm: int
    weight_kg: int
    primary_position: str


@dataclass(frozen=True)
class DeletePlayerCommand:
    """Input contract for deleting a player by identifier."""

    id: str


@dataclass(frozen=True)
class AssignPlayerTeamCommand:
    """Input contract for assigning a player to a team."""

    player_id: str
    team_id: str


class CreatePlayerUseCase:
    """Creates a new player inside a single transaction boundary."""

    def __init__(self, *, players: PlayerRepositoryPort, ids: IdGeneratorPort, uow: UnitOfWorkPort) -> None:
        self._players = players
        self._ids = ids
        self._uow = uow

    def execute(self, command: CreatePlayerCommand) -> Player:
        """Persists a new player with generated identifier and no initial team."""

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
    """Read-only listing of all players."""

    def __init__(self, *, players: PlayerRepositoryPort) -> None:
        self._players = players

    def execute(self) -> list[Player]:
        return self._players.list_all()


class ListPlayersByTeamUseCase:
    """Read-only listing scoped to one team identifier."""

    def __init__(self, *, players: PlayerRepositoryPort) -> None:
        self._players = players

    def execute(self, team_id: str) -> list[Player]:
        return self._players.list_by_team(team_id)


class UpdatePlayerUseCase:
    """Updates a player atomically and maps missing rows to domain-safe errors."""

    def __init__(self, *, players: PlayerRepositoryPort, uow: UnitOfWorkPort) -> None:
        self._players = players
        self._uow = uow

    def execute(self, command: UpdatePlayerCommand) -> Player:
        """Returns the updated player or raises PLAYER_NOT_FOUND when absent."""

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
    """Deletes a player atomically.

    Repository `False` is translated to PLAYER_NOT_FOUND so adapters expose a
    stable application error contract.
    """

    def __init__(self, *, players: PlayerRepositoryPort, uow: UnitOfWorkPort) -> None:
        self._players = players
        self._uow = uow

    def execute(self, command: DeletePlayerCommand) -> None:
        with self._uow.transaction():
            deleted = self._players.delete(command.id)
        if not deleted:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")


class AssignPlayerTeamUseCase:
    """Assigns a player to an existing team in one transaction.

    Team existence is validated first to preserve error semantics: missing team
    takes precedence over missing player.
    """

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
