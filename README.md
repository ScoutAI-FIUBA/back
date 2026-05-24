# ScoutAI Backend

FastAPI backend with hexagonal architecture.

## Run locally

### Docker compose (recommended)

```bash
cp .env.example .env
docker compose up --build
curl http://127.0.0.1:8005/health
curl http://127.0.0.1:8005/db-health
```

### Bare Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/wait_for_db.py
python scripts/apply_migrations.py
uvicorn src.interfaces.http.main:app --reload
```

## Tests

```bash
pytest -m "not integration" tests

DATABASE_URL=postgresql://postgres:postgres@localhost:5435/scoutai_dev \
  pytest -q -m integration tests/integration
```

## Deploy

Production config lives in `render.yaml` and `.env.example`. Set env vars in the Render dashboard before deploying.

## API endpoint inventory

- Health
  - `GET /health`
  - `GET /db-health`
- Auth (`specs/api/auth.md`)
  - `POST /auth/register`
  - `POST /auth/login`
  - `POST /auth/refresh`
  - `POST /auth/logout`
  - `GET /auth/me`
  - `DELETE /auth/me`
- Players (`specs/api/players.md`)
  - `POST /players`
  - `GET /players`
  - `PUT /players/{player_id}`
  - `DELETE /players/{player_id}`

## Structure

- `src/domain/` — core business models and rules
- `src/application/` — use cases and port contracts
- `src/infrastructure/` — concrete external implementations
- `src/interfaces/http/` — FastAPI transport layer
- `src/ai/` — AI-oriented ports and adapters
- `scripts/` — `wait_for_db.py`, `apply_migrations.py`
- `specs/` — PRD and product specs
