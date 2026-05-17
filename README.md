# FastAPI Hexagonal Backend Skeleton

Minimal backend scaffold with hexagonal boundaries and AI adapter placeholders.

## Run locally

1. Create environment and install dependencies:
   - `python -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. Start API:
   - `uvicorn src.interfaces.http.main:app --reload`
3. Check health:
   - `GET http://127.0.0.1:8000/health`

## Docker local stack (API + PostgreSQL)

1. Copy environment file and set local secrets:
   - `cp .env.example .env`
2. Start stack:
   - `docker compose up --build`
3. Check health:
   - `curl http://127.0.0.1:8000/health`
4. Follow logs:
   - `docker compose logs -f api db`
5. Stop and remove containers:
   - `docker compose down`

### Run tests against local stack

- Run integration tests (expects DB + migrations from compose startup):
  - `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/scoutai_dev pytest -q -m integration tests/integration`

## Structure

- `src/domain/` core business models and rules (framework-agnostic)
- `src/application/` use cases and port contracts
- `src/infrastructure/` concrete external implementations
- `src/interfaces/http/` FastAPI transport layer
- `src/ai/` AI-oriented ports and adapters
- `specs/` PRD and product specs
- `.engram/` shared Engram decision snapshots for team visibility
- `.opencode/` placeholders for future project-specific skills
