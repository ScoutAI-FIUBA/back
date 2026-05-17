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

## Structure

- `src/domain/` core business models and rules (framework-agnostic)
- `src/application/` use cases and port contracts
- `src/infrastructure/` concrete external implementations
- `src/interfaces/http/` FastAPI transport layer
- `src/ai/` AI-oriented ports and adapters
- `specs/` PRD and product specs
- `ops/engram/` shared Engram decision snapshots for team visibility
- `.opencode/` placeholders for future project-specific skills
