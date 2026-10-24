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
from src.domain.players.entities import Player, build_empty_player_stats
from src.domain.players.positions import VALID_POSITION_CODES, is_valid_position


def _validate_position(code: str | None) -> None:
    # An omitted position is fine; a given one must still be a known code.
    if code is not None and not is_valid_position(code):
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
    birth_date: date | None = None
    height_cm: int | None = None
    weight_kg: int | None = None
    primary_position: str | None = None
    jersey_number: str | None = None


@dataclass(frozen=True)
class UpdatePlayerCommand:
    user_id: str
    id: str
    first_name: str
    last_name: str
    birth_date: date | None = None
    height_cm: int | None = None
    weight_kg: int | None = None
    primary_position: str | None = None
    jersey_number: str | None = None


@dataclass(frozen=True)
class DeletePlayerCommand:
    user_id: str
    id: str


@dataclass(frozen=True)
class AssignPlayerTeamCommand:
    user_id: str
    player_id: str
    team_id: str


@dataclass(frozen=True)
class RosterPlayerInput:
    first_name: str
    last_name: str
    jersey_number: str


@dataclass(frozen=True)
class CreateTeamRosterCommand:
    user_id: str
    team_id: str
    players: list[RosterPlayerInput]


@dataclass(frozen=True)
class CreateTeamRosterResult:
    created: list[Player]
    # Jersey numbers the team already had; those players were left as they were.
    skipped_jersey_numbers: list[str]


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
            jersey_number=command.jersey_number,
            owner_user_id=command.user_id,
            team_id=None,
            stats=build_empty_player_stats(),
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
                jersey_number=command.jersey_number,
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


class CreateTeamRosterUseCase:
    """Creates name-and-jersey-only players straight into a team, all or nothing.

    Safe to repeat: a jersey the team already has is skipped, not duplicated.
    """

    def __init__(
        self,
        *,
        players: PlayerRepositoryPort,
        teams: TeamRepositoryPort,
        ids: IdGeneratorPort,
        uow: UnitOfWorkPort,
    ) -> None:
        self._players = players
        self._teams = teams
        self._ids = ids
        self._uow = uow

    def execute(self, command: CreateTeamRosterCommand) -> CreateTeamRosterResult:
        created: list[Player] = []
        skipped: list[str] = []
        with self._uow.transaction():
            if not self._teams.lock_owned(team_id=command.team_id, owner_user_id=command.user_id):
                raise PlayerError(code=TEAM_NOT_FOUND, message="Team not found")
            taken = {
                player.jersey_number
                for player in self._players.list_by_owner_and_team(
                    owner_user_id=command.user_id, team_id=command.team_id
                )
                if player.jersey_number is not None
            }
            for entry in command.players:
                if entry.jersey_number in taken:
                    skipped.append(entry.jersey_number)
                    continue
                taken.add(entry.jersey_number)
                created.append(
                    self._players.create(
                        Player(
                            id=self._ids.new_id(),
                            first_name=entry.first_name,
                            last_name=entry.last_name,
                            jersey_number=entry.jersey_number,
                            owner_user_id=command.user_id,
                            team_id=command.team_id,
                            stats=build_empty_player_stats(),
                        )
                    )
                )
        return CreateTeamRosterResult(created=created, skipped_jersey_numbers=skipped)


class GetPlayerStatsUseCase:
    def __init__(self, *, players: PlayerRepositoryPort) -> None:
        self._players = players

    def execute(self, *, user_id: str, player_id: str) -> Player:
        player = self._players.get_by_id(player_id=player_id, owner_user_id=user_id)
        if player is None:
            raise PlayerError(code=PLAYER_NOT_FOUND, message="Player not found")
        return player
