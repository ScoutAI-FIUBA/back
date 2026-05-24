from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager

from src.domain.players.entities import Player


class PlayerRepositoryPort(ABC):
    @abstractmethod
    def create(self, player: Player) -> Player:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> list[Player]:
        raise NotImplementedError

    @abstractmethod
    def update(self, player: Player) -> Player | None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, player_id: str) -> bool:
        raise NotImplementedError


class UnitOfWorkPort(ABC):
    @abstractmethod
    def transaction(self) -> AbstractContextManager[None]:
        raise NotImplementedError


class IdGeneratorPort(ABC):
    @abstractmethod
    def new_id(self) -> str:
        raise NotImplementedError
