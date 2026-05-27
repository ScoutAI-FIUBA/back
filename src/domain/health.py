"""Minimal domain health status primitives."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HealthStatus:
    """Health response value object.

    `status` defaults to `"ok"` and is treated as an immutable snapshot.
    """

    status: str = "ok"
