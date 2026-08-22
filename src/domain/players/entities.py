"""Player aggregate root entities for the domain layer.

These models are intentionally immutable snapshots and do not perform
normalization/validation by themselves. Upstream mappers/services are expected
to provide already validated identifiers and measurements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


EMPTY_PLAYER_STATS: dict[str, int] = {
    "games_played": 0,
    "wins": 0,
    "losses": 0,
    "points": 0,
    "rebounds": 0,
    "assists": 0,
    "steals": 0,
    "blocks": 0,
    "turnovers": 0,
}


def build_empty_player_stats() -> dict[str, int]:
    return dict(EMPTY_PLAYER_STATS)


@dataclass(frozen=True)
class Player:
    """Represents a persisted player identity and profile attributes.

    Invariants expected by callers:
    - `id` is a stable repository identity.
    - `team_id` is `None` for free agents, otherwise references an existing team.
    - Anthropometric values use metric units (`height_cm`, `weight_kg`).
    - `jersey_number` is one or two digits as text, or `None` when unassigned.
    """

    id: str
    first_name: str
    last_name: str
    birth_date: date
    height_cm: int
    weight_kg: int
    primary_position: str
    jersey_number: str | None = None
    owner_user_id: str = ""
    team_id: str | None = None
    stats: dict[str, int] = field(default_factory=build_empty_player_stats)
