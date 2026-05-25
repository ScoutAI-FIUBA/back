from __future__ import annotations

from abc import ABC, abstractmethod
from src.application.common.ports import IdGeneratorPort, UnitOfWorkPort

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

    @abstractmethod
    def assign_team(self, *, player_id: str, team_id: str) -> Player | None:
        raise NotImplementedError

    @abstractmethod
    def list_by_team(self, team_id: str) -> list[Player]:
        raise NotImplementedError
