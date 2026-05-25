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

Team CRUD integration coverage lives in `tests/integration/test_team_crud_integration.py`.

## API endpoints

### Health

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/health` | Service health status. |
| `GET` | `/db-health` | Database connectivity health check. |

### Auth

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/auth/register` | Register a user account. |
| `POST` | `/auth/login` | Authenticate and issue access token + refresh cookie. |
| `POST` | `/auth/refresh` | Rotate refresh session and return a new access token. |
| `POST` | `/auth/logout` | Revoke refresh session and clear refresh cookie. |
| `GET` | `/auth/me` | Return current authenticated user. |
| `DELETE` | `/auth/me` | Delete current authenticated user. |

### Teams

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/teams` | Create team. |
| `GET` | `/teams` | List teams. |
| `PUT` | `/teams/{team_id}` | Update team by UUID. |
| `DELETE` | `/teams/{team_id}` | Delete team by UUID. |

- Teams contract and examples: `specs/api/teams.md`.
- Teams persistence: migration `src/infrastructure/team/migrations/001_team_foundation.sql` creates `teams` table with required fields:
  - `id` (UUID, primary key)
  - `name` (TEXT, not null)
  - `short_name` (TEXT, not null)
  - `city` (TEXT, not null)
  - `country` (TEXT, not null)
  - `created_at` (TIMESTAMPTZ, not null)

### Players

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/players` | Create player. |
| `GET` | `/players` | List players; use `team_id` query param to filter by team. |
| `PUT` | `/players/{player_id}` | Update player by UUID. |
| `PUT` | `/players/{player_id}/team/{team_id}` | Associate player with team UUID. |
| `DELETE` | `/players/{player_id}` | Delete player by UUID. |

- Players contract and examples: `specs/api/players.md`.
- Player-team association persistence: `src/infrastructure/team/migrations/002_player_team_association.sql` adds nullable `players.team_id` foreign key to `teams(id)`.

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
  - `PUT /players/{player_id}/team/{team_id}`
  - `DELETE /players/{player_id}`

## Structure

- `src/domain/` — core business models and rules
- `src/application/` — use cases and port contracts
- `src/infrastructure/` — concrete external implementations
- `src/interfaces/http/` — FastAPI transport layer
- `src/ai/` — AI-oriented ports and adapters
- `scripts/` — `wait_for_db.py`, `apply_migrations.py`
- `specs/` — PRD and product specs
