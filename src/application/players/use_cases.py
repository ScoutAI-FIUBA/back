from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.application.players.errors import PLAYER_NOT_FOUND, PlayerError
from src.application.players.ports import IdGeneratorPort, PlayerRepositoryPort, UnitOfWorkPort
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
        )
        with self._uow.transaction():
            return self._players.create(player)


class ListPlayersUseCase:
    def __init__(self, *, players: PlayerRepositoryPort) -> None:
        self._players = players

    def execute(self) -> list[Player]:
        return self._players.list_all()


class UpdatePlayerUseCase:
    def __init__(self, *, players: PlayerRepositoryPort, uow: UnitOfWorkPort) -> None:
        self._players = players
        self._uow = uow

    def execute(self, command: UpdatePlayerCommand) -> Player:
        with self._uow.transaction():
            updated = self._players.update(
                Player(
                    id=command.id,
                    first_name=command.first_name,
                    last_name=command.last_name,
                    birth_date=command.birth_date,
                    height_cm=command.height_cm,
                    weight_kg=command.weight_kg,
                    primary_position=command.primary_position,
                )
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
