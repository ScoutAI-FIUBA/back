from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.application.common.ports import IdGeneratorPort, UnitOfWorkPort
from src.domain.matches.entities import Match, MatchParticipant, MatchStatsView, TeamStatsSummary


class MatchRepositoryPort(ABC):
    @abstractmethod
    def create(self, match: Match) -> Match:
        raise NotImplementedError

    @abstractmethod
    def list_by_owner(self, *, owner_user_id: str, team_id: str | None = None) -> list[Match]:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, *, match_id: str, owner_user_id: str) -> Match | None:
        raise NotImplementedError

    @abstractmethod
    def replace_stats(
        self,
        *,
        match_id: str,
        owner_user_id: str,
        stats: Any | None,
        winner_team_id: str | None,
        participants: list[MatchParticipant],
    ) -> MatchStatsView | None:
        raise NotImplementedError

    @abstractmethod
    def get_stats(self, *, match_id: str, owner_user_id: str) -> MatchStatsView | None:
        raise NotImplementedError

    @abstractmethod
    def list_player_matches(self, *, owner_user_id: str, player_id: str) -> list[Match]:
        raise NotImplementedError

    @abstractmethod
    def get_team_stats(self, *, owner_user_id: str, team_id: str) -> TeamStatsSummary:
        raise NotImplementedError


__all__ = ["IdGeneratorPort", "UnitOfWorkPort", "MatchRepositoryPort"]
