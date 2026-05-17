from src.application.ports import HealthQueryPort
from src.domain.health import HealthStatus


class InMemoryHealthAdapter(HealthQueryPort):
    def get_status(self) -> HealthStatus:
        return HealthStatus()
