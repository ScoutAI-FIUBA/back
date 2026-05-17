from fastapi import FastAPI

from src.application.use_cases import GetHealthStatus
from src.infrastructure.health_adapter import InMemoryHealthAdapter


def create_app() -> FastAPI:
    app = FastAPI(title="ScoutAI Backend", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        use_case = GetHealthStatus(InMemoryHealthAdapter())
        status = use_case.execute()
        return {"status": status.status}

    return app


app = create_app()
