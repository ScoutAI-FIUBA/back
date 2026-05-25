from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    short_name: str
    city: str
    country: str
    created_at: datetime
