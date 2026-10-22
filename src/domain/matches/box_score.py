from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Shooting:
    made: int
    attempted: int


@dataclass(frozen=True)
class BoxScoreLine:
    """One row of a federation box score (a player or a team total)."""

    minutes_seconds: int
    points: int
    two_point: Shooting
    three_point: Shooting
    free_throw: Shooting
    rebounds_defensive: int
    rebounds_offensive: int
    rebounds_total: int
    assists: int
    steals: int
    turnovers: int
    blocks: int
    blocks_received: int
    fouls: int
    fouls_drawn: int
    valuation: int
    plus_minus: int


@dataclass(frozen=True)
class BoxScorePlayer:
    jersey_number: str | None
    name: str
    line: BoxScoreLine

    @property
    def played(self) -> bool:
        return self.line.minutes_seconds > 0


@dataclass(frozen=True)
class BoxScoreTeam:
    name: str
    players: list[BoxScorePlayer]
    totals: BoxScoreLine | None


@dataclass(frozen=True)
class ParsedBoxScore:
    """A parsed federation box score. Teams are in sheet order (first = home)."""

    title: str | None
    home_name_hint: str | None
    away_name_hint: str | None
    competition: str | None
    teams: list[BoxScoreTeam] = field(default_factory=list)
