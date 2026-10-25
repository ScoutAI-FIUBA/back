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

### Matches (edit and video link)

| Method | Path | Auth required | Purpose |
| --- | --- | --- | --- |
| `PATCH` | `/matches/{match_id}` | Yes | Edit only `match_date` and `description` (`null` clears the description, an omitted field is kept; max 2000 chars). Teams, winner, stats and participants are untouched. `404 MATCH_NOT_FOUND` for missing or foreign matches. There is no `DELETE /matches/{id}`. |
| `PUT` | `/videos/{video_id}/match` | Yes | Link a video to a match (`{team_id, match_id}`) or clear it (`match_id: null`). See `specs/api/videos.md`. |

- Videos expose `match_id` (nullable). Migration `src/infrastructure/video/migrations/004_video_match_link.sql` is additive and idempotent; back up the database before deploying because the container start command applies migrations.

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
| `POST` | `/players/bulk` | Yes | Create up to 30 name-and-jersey-only players into one team (skips jerseys the team already has). |
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

- Only shots by roster players are kept, tied by confirmed jersey number on the job's marked team side. If several
  tracks of one video link to the same roster player, their numbers are added up into one row for that video.
- Rows are replaced per video by the video's latest DONE job, so analysing a video twice never double-counts.
  Setting the side on an older job of a video reports `player_stats_sync: "not_latest"` and changes nothing.
- A re-run's DONE callback clears the video's player rows (sides are not stable between runs: side 0 of the old run
  is not side 0 of the new one) until the scout sets "our team" on the new job; the old numbers do not linger.
- Each finished analysis carries an invisible marker (`processing_jobs.player_stats_synced_version` and
  `player_stats_synced_at`, migration `007_processing_jobs_player_stats_sync.sql`; never returned by any API) that
  says "player stats for this analysis are done". It is written by the sync itself, inside the same transaction as
  the rows, and only if no roster change cleared it while the sync was reading (`player_stats_synced_at` is the
  database-clock time of the last marker change). A background catch-up (`CatchUpPlayerAnalysisUseCase`) syncs every DONE analysis that has a side and no
  marker for the current `CALC_VERSION` (newest first, up to 200 per run): at startup (this is the backfill of
  analyses that predate the feature; a daemon thread, so it never delays startup or health checks), after
  `GET /players` finds something pending (checked at most once per user per 60 s), and after a roster change.
  Bumping `CALC_VERSION` makes every analysis pending again. `GET /players` serves `players.stats` as kept (it never
  reads object storage while a user waits) and every player in the response includes `stats`.
- A sync that began before a marker change (a roster change cleared it, or a newer sync already finished) keeps
  nothing (`stale`; the team-side response reports it as `side_changed`) and the analysis is redone on the next
  catch-up. The sync (not the screens) also fails whenever object storage itself errors on any file, including the
  optional ones (`player_summary.json`, `results.json`, positions), so a transient error never shrinks the kept rows;
  a file that is truly missing (`NoSuchKey`/404) is still ordinary.
- Two things only checkable in production: run `SHOW idle_in_transaction_session_timeout;` on the app role (a short
  timeout kills the catch-up's lock transaction mid-run; that is safe, the run just logs "catch-up failed" and
  the next trigger resumes), and confirm that a missing R2 key answers `NoSuchKey`/404 and not 403 (a 403 would be
  treated as a storage failure and the analysis would stay pending, retried every 10 minutes).
- A jersey or roster change (creating, editing, moving to another team or deleting a player) clears that team's
  markers and catches the team up in the background (best effort, never fails the request), so every analysis of
  the team, old ones included, is linked to the roster as it is now. A roster edit that lands while a sync is
  running can leave one analysis linked the old way for a moment; the next roster edit or re-saving the side fixes it.
- Only one catch-up runs at a time across workers and instances (transaction-level `pg_try_advisory_xact_lock` on a dedicated connection, so it also works behind a transaction pooler; the others
  skip and the next trigger picks the work up). An analysis whose sync fails (for example its result files are gone
  from object storage) stays unmarked and is not retried for 10 minutes (in-memory memo, per process).
- Syncs are serialised per video in the database (advisory lock) and re-check, inside that lock, that the job is still
  the latest DONE one and that its side did not change meanwhile; `players.stats` is recomputed under a row lock so
  parallel syncs of different videos of one player never lose each other's totals. Soft-deleting a video refreshes
  its players' `players.stats` (hard deletes of jobs and videos are not exposed by the API).
- Rows ignore soft-deleted videos and are removed with the player or the job. A shot whose coordinates, shot value
  or distance are missing or not finite is not stored (and counted as skipped in the sync result).
- A problem while keeping these rows never fails the job callback. `PUT /jobs/{id}/our-team` adds
  `"player_stats_sync"` to its response: `ok`, `no_side`, `not_latest`, `side_changed` (also when a concurrent roster change made the result obsolete), `not_ready`, `job_not_found`
  or `failed` (the sync is best effort; `failed` is logged and can be retried by saving the side again).
- Units. `players.stats.*.percentage` keeps the existing integer percent (0 to 100) and its per-game values are whole
  numbers; `GET /players/{id}/analysis-stats` reports every shooting `pct` as a fraction (0 to 1, or null without
  attempts), like the other stats endpoints, and exact totals.
- `shot_value` is what a shot is worth by where it was taken (2 or 3), also when it missed; it is not points scored.
  `seconds_on_screen` is the time the player was visible in the video, in seconds, not minutes played.
  `timestamp_seconds` counts from the start of the analysed video. `calc_version` is the version of the court/zone
  rules the rows were computed with.
- `GET /players/{id}/shot-chart` returns the player, the court, every shot (each with a `shot_key` unique among the
  player's shots, outcome confidence/source and release/resolved timestamps) and a coverage summary. Both endpoints
  have pydantic response models in `src/interfaces/http/schemas/player_analysis.py`.
- Deploy note: there is no backfill command. Analyses that finished before this existed are built the next time the
  scout saves "our team" on them. Development databases that applied an earlier version of
  `006_player_analysis_stats.sql` must be recreated: the migration changed before it shipped (it is not edited by a
  later migration).

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
