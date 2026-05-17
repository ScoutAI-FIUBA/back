from src.application.ports import HealthQueryPort
from src.domain.health import HealthStatus


class GetHealthStatus:
    def __init__(self, health_query: HealthQueryPort) -> None:
        self._health_query = health_query

    def execute(self) -> HealthStatus:
        return self._health_query.get_status()
