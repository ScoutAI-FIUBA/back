"""Shared application ports."""

from abc import ABC, abstractmethod

from src.domain.health import HealthStatus


class HealthQueryPort(ABC):
    """Read contract for health status probes.

    Implementations may aggregate infrastructure checks, but callers only depend
    on the `HealthStatus` result.
    """

    @abstractmethod
    def get_status(self) -> HealthStatus:
        raise NotImplementedError
