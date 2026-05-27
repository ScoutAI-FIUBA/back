"""Cross-cutting application use cases."""

from src.application.ports import HealthQueryPort
from src.domain.health import HealthStatus


class GetHealthStatus:
    """Reads system health from the configured health query port.

    This use case is intentionally side-effect free and acts as the application
    boundary for operational health checks.
    """

    def __init__(self, health_query: HealthQueryPort) -> None:
        self._health_query = health_query

    def execute(self) -> HealthStatus:
        return self._health_query.get_status()
