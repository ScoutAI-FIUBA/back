from abc import ABC, abstractmethod

from src.domain.health import HealthStatus


class HealthQueryPort(ABC):
    @abstractmethod
    def get_status(self) -> HealthStatus:
        raise NotImplementedError
