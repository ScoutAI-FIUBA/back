from __future__ import annotations

"""Team application ports.

These abstractions describe team persistence, identity generation, and time
sources consumed by team use cases.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.team.entities import Team


TEAM_DELETE_CONFLICT_KIND_MATCH = "match_related"
TEAM_DELETE_CONFLICT_KIND_GENERIC = "generic"


class TeamDeleteConflictError(Exception):
    def __init__(self, message: str, *, kind: str = TEAM_DELETE_CONFLICT_KIND_GENERIC) -> None:
        self.kind = kind
        super().__init__(message)


class TeamRepositoryPort(ABC):
    """Persistence contract for team aggregates."""

    @abstractmethod
    def create(self, team: Team) -> Team:
        raise NotImplementedError

    @abstractmethod
    def list_by_owner(self, *, owner_user_id: str) -> list[Team]:
        raise NotImplementedError

    @abstractmethod
    def update(
        self,
        team_id: str,
        *,
        owner_user_id: str,
        name: str,
        short_name: str,
        city: str,
        country: str,
        is_own: bool | None = None,
    ) -> Team | None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, team_id: str, *, owner_user_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def is_owned_by(self, *, team_id: str, owner_user_id: str) -> bool:
        raise NotImplementedError


class TeamClockPort(ABC):
    """Time source contract used to create deterministic timestamps."""

    @abstractmethod
    def now(self) -> datetime:
        raise NotImplementedError


class TeamIdGeneratorPort(ABC):
    """Identifier generator contract for team entities."""

    @abstractmethod
    def new_id(self) -> str:
        raise NotImplementedError
