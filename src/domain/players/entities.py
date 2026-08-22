"""Player aggregate root entities for the domain layer.

These models are intentionally immutable snapshots and do not perform
normalization/validation by themselves. Upstream mappers/services are expected
to provide already validated identifiers and measurements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


JSONPrimitive = None | bool | int | float | str
JSONValue = JSONPrimitive | list["JSONValue"] | dict[str, "JSONValue"]
PlayerStats = dict[str, JSONValue]


def _build_total_stat() -> dict[str, int]:
    return {"total": 0, "per_game": 0}


def _build_shooting_stat() -> dict[str, JSONValue]:
    return {
        "made_total": 0,
        "attempted_total": 0,
        "per_game": {"made": 0, "attempted": 0},
        "percentage": 0,
    }


def build_empty_player_stats() -> PlayerStats:
    return {
        "games_played": 0,
        "record": {"wins": 0, "losses": 0},
        "points": _build_total_stat(),
        "rebounds": _build_total_stat(),
        "assists": _build_total_stat(),
        "steals": _build_total_stat(),
        "blocks": _build_total_stat(),
        "turnovers": _build_total_stat(),
        "field_goals": _build_shooting_stat(),
        "two_point": _build_shooting_stat(),
        "three_point": _build_shooting_stat(),
        "free_throws": _build_shooting_stat(),
    }


EMPTY_PLAYER_STATS: PlayerStats = build_empty_player_stats()


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
    stats: PlayerStats = field(default_factory=build_empty_player_stats)
