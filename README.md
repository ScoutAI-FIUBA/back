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
uvicorn src.interfaces.http.main:create_app --factory --reload
```

## Tests

```bash
pytest -m "not integration" tests

DATABASE_URL=postgresql://postgres:postgres@localhost:5435/scoutai_dev \
  pytest -q -m integration tests/integration
```

Team CRUD integration coverage lives in `tests/integration/test_team_crud_integration.py`; player analysis stats in
`tests/integration/test_player_analysis_integration.py`. The integration guard only accepts local hosts, so for a
throwaway database without a hostname (for example a Unix-socket Postgres) set `INTEGRATION_DB_ALLOW_REMOTE=1`.

## API endpoints

Auth policy: all HTTP endpoints require a Bearer access token by default. Current public whitelist (no auth): `/health`, `/db-health`, `/auth/register`, `/auth/login`, `/auth/refresh`.

Note: CORS preflight `OPTIONS` requests are also allowed without auth.

### Health

| Method | Path | Auth required | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | No | Service health status. |
| `GET` | `/db-health` | No | Database connectivity health check. |

### Auth

| Method | Path | Auth required | Purpose |
| --- | --- | --- | --- |
| `POST` | `/auth/register` | No | Register a new user account. |
| `POST` | `/auth/login` | No | Authenticate user and issue access token + refresh cookie. |
| `POST` | `/auth/refresh` | No | Rotate refresh session and return a new access token. |
| `POST` | `/auth/logout` | Yes | Revoke refresh session (if present) and clear refresh cookie. |
| `GET` | `/auth/me` | Yes | Return the current authenticated user profile. |
| `DELETE` | `/auth/me` | Yes | Hard-delete the current authenticated user. |

### Teams

| Method | Path | Auth required | Purpose |
| --- | --- | --- | --- |
| `POST` | `/teams` | Yes | Create a team. |
| `GET` | `/teams` | Yes | List all teams. |
| `PUT` | `/teams/{team_id}` | Yes | Update a team by UUID. |
| `DELETE` | `/teams/{team_id}` | Yes | Delete a team by UUID. |

- Teams contract and examples: `specs/api/teams.md`.
- Teams persistence: migration `src/infrastructure/team/migrations/001_team_foundation.sql` creates `teams` table with required fields:
  - `id` (UUID, primary key)
  - `name` (TEXT, not null)
  - `short_name` (TEXT, not null)
  - `city` (TEXT, not null)
  - `country` (TEXT, not null)
  - `created_at` (TIMESTAMPTZ, not null)

### Clip collections

| Method | Path | Auth required | Purpose |
| --- | --- | --- | --- |
| `POST` | `/videos/{video_id}/collections` | Yes | Create a private clip collection under one owned video. |
| `GET` | `/videos/{video_id}/collections` | Yes | List private collections for one owned video. |
| `GET` | `/videos/{video_id}/collections/{collection_id}` | Yes | Get collection metadata plus ordered clips. |
| `POST` | `/videos/{video_id}/collections/{collection_id}/clips` | Yes | Add one virtual clip range (`start_ms`, `end_ms`). |
| `POST` | `/videos/{video_id}/collections/{collection_id}/clips/batch` | Yes | Add multiple virtual clip ranges in one request. |
| `POST` | `/videos/{video_id}/collections/{collection_id}/clips/{item_id}/export` | Yes | Re-encode and return a cached MP4 download URL for one clip item. |
| `DELETE` | `/videos/{video_id}/collections/{collection_id}/clips/{item_id}` | Yes | Delete one virtual clip item row. |

- Clip collections contract and examples: `specs/api/clip-collections.md`.
- Clip persistence uses dedicated tables from `src/infrastructure/clip_collections/migrations/001_clip_collections_foundation.sql`.
- Clip exports require `ffmpeg` in the runtime image and an object-storage lifecycle rule that deletes `exports/` objects after 7 days.

### Players

| Method | Path | Auth required | Purpose |
| --- | --- | --- | --- |
| `POST` | `/players` | Yes | Create a player. |
| `GET` | `/players` | Yes | List players; optional `team_id` query param filters by team UUID. |
| `PUT` | `/players/{player_id}` | Yes | Update a player by UUID. |
| `PUT` | `/players/{player_id}/team/{team_id}` | Yes | Assign a player to a team using UUIDs. |
| `DELETE` | `/players/{player_id}` | Yes | Delete a player by UUID. |
| `GET` | `/players/{player_id}/shot-chart` | Yes | Every shot the player took across their analysed videos, with court position (`x_m`, `y_m`), `made` and `result` (made / missed / unknown) for green and red dots. |
| `GET` | `/players/{player_id}/analysis-stats` | Yes | Totals the video analyses measured for the player (games, points, FG/2P/3P, per-zone and per-shot-type, distance), across all their videos. |

#### Player stats from video analyses

When an analysis finishes, and whenever the scout marks which side is their team on a job, what the
analysis measured for each roster player is kept in `player_analysis_games` and
`player_analysis_shots` (migration `006_player_analysis_stats.sql`), and the measured fields of
`players.stats` are filled (`games_played`, `points`, `field_goals`, `two_point`, `three_point`;
rebounds, assists, steals, blocks, turnovers and free throws are not measured and stay 0).

- Only shots by roster players are kept, tied by confirmed jersey number on the job's marked team side.
- Only the latest finished analysis of each video counts, so analysing a video twice never double-counts.
- Rows ignore soft-deleted videos and are removed with the player or the job.
- A problem while keeping these rows never fails the job callback. Analyses that finished before this existed are
  built the next time the scout saves "our team" on them (re-selecting the side triggers the same sync).
- `players.stats` stores whole-number per-game averages (the existing contract); exact figures are in `analysis-stats`.

- Players contract and examples: `specs/api/players.md`.
- Player-team association persistence: `src/infrastructure/team/migrations/002_player_team_association.sql` adds nullable `players.team_id` foreign key to `teams(id)`.

## Deploy

Production config lives in `render.yaml` and `.env.example`. Set env vars in the Render dashboard before deploying.

## Structure

- `src/domain/` — core business models and rules
- `src/application/` — use cases and port contracts
- `src/infrastructure/` — concrete external implementations
- `src/interfaces/http/` — FastAPI transport layer
- `src/ai/` — AI-oriented ports and adapters
- `scripts/` — `wait_for_db.py`, `apply_migrations.py`
- `specs/` — PRD and product specs
