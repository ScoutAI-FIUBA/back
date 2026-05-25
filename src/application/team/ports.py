from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.team.entities import Team


class TeamRepositoryPort(ABC):
    @abstractmethod
    def create(self, team: Team) -> Team:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> list[Team]:
        raise NotImplementedError

    @abstractmethod
    def update(self, team_id: str, *, name: str, short_name: str, city: str, country: str) -> Team | None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, team_id: str) -> bool:
        raise NotImplementedError


class TeamClockPort(ABC):
    @abstractmethod
    def now(self) -> datetime:
        raise NotImplementedError


class TeamIdGeneratorPort(ABC):
    @abstractmethod
    def new_id(self) -> str:
        raise NotImplementedError
