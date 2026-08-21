"""Player aggregate root entities for the domain layer.

These models are intentionally immutable snapshots and do not perform
normalization/validation by themselves. Upstream mappers/services are expected
to provide already validated identifiers and measurements.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


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
