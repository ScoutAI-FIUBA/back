"""Team entities used by the domain layer.

Instances are immutable read models for business logic and must be created from
already validated source data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Team:
    """Represents a football team with stable identity and display metadata.

    Invariants expected by callers:
    - `id` is globally unique and stable over time.
    - `short_name` is a compact label used in constrained UIs.
    - `created_at` is the canonical creation timestamp from persistence.
    """

    id: str
    name: str
    short_name: str
    city: str
    country: str
    owner_user_id: str
    created_at: datetime
    is_own: bool = False
