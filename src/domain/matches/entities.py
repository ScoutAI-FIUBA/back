from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


TeamSide = Literal["HOME", "AWAY"]


@dataclass(frozen=True)
class Match:
    id: str
    owner_user_id: str
    home_team_id: str
    away_team_id: str
    match_date: date
    description: str | None
    winner_team_id: str | None = None
    stats: Any | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class MatchParticipant:
    id: str
    match_id: str
    owner_user_id: str
    team_side: TeamSide
    display_name: str
    player_id: str | None = None
    jersey_number: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class MatchStatsView:
    match: Match
    participants: list[MatchParticipant] = field(default_factory=list)


@dataclass(frozen=True)
class TeamMatchResultSummary:
    match_id: str
    match_date: date
    home_team_id: str
    away_team_id: str
    winner_team_id: str | None
    description: str | None
    result: str


@dataclass(frozen=True)
class TeamStatsSummary:
    team_id: str
    matches_played: int
    wins: int
    losses: int
    results: list[TeamMatchResultSummary] = field(default_factory=list)
