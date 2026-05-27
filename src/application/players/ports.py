from __future__ import annotations

"""Player application ports.

Ports define the persistence and transaction contracts required by player use
cases, independent of concrete storage technologies.
"""

from abc import ABC, abstractmethod
from datetime import date
from src.application.common.ports import IdGeneratorPort, UnitOfWorkPort

from src.domain.players.entities import Player


class PlayerRepositoryPort(ABC):
    """Persistence contract for player aggregates."""

    @abstractmethod
    def create(self, player: Player) -> Player:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> list[Player]:
        raise NotImplementedError

    @abstractmethod
    def update(
        self,
        *,
        player_id: str,
        first_name: str,
        last_name: str,
        birth_date: date,
        height_cm: int,
        weight_kg: int,
        primary_position: str,
    ) -> Player | None:
        """Returns updated player or `None` when `player_id` does not exist."""

        raise NotImplementedError

    @abstractmethod
    def delete(self, player_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def assign_team(self, *, player_id: str, team_id: str) -> Player | None:
        """Assigns team and returns player, or `None` if player is missing."""

        raise NotImplementedError

    @abstractmethod
    def list_by_team(self, team_id: str) -> list[Player]:
        raise NotImplementedError
