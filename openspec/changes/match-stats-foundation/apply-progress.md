# Apply Progress: Match Stats Foundation

## Mode
- Standard

## Completed Tasks
- [x] 1.1 Create `src/infrastructure/matches/migrations/001_match_stats_foundation.sql` for `matches`/`match_participants`, nullable `winner_team_id`, ownership FKs, delete rules, and indexes.
- [x] 1.2 Add `src/infrastructure/players/migrations/002_player_stats_foundation.sql` to add `players.stats`, backfill existing rows, and enforce the V1 default aggregate.
- [x] 1.3 Register `src/infrastructure/matches/migrations` in `scripts/apply_migrations.py` and in `tests/integration/test_{player_crud,video_management,clip_collections,team_crud}_integration.py` bootstrap helpers.
- [x] 1.4 Add `src/domain/matches/entities.py` and extend `src/domain/players/entities.py` with the V1 stats shape used by persistence and responses.
- [x] 2.1 Create `src/application/matches/{ports,use_cases,errors}.py` for create/list/get, stats replace, player-history, and team-summary flows with owner checks.
- [x] 2.2 Extend `src/application/players/{ports,use_cases}.py` so create/get flows initialize and return global `players.stats` without recomputation.
- [x] 2.3 Implement `src/infrastructure/matches/postgres_repository.py` for `POST /matches`, `GET /matches`, `GET /matches/{id}`, stats replace, participant replace, player history, and team summary queries.
- [x] 2.4 Update `src/infrastructure/players/postgres_player_repository.py` to insert/select/map `players.stats`; verify new rows and migrated rows return the same default payload.
- [x] 2.5 Update `src/infrastructure/team/postgres_repository.py` plus team application error handling to map team-delete FK conflicts to HTTP 409 `TEAM_HAS_MATCHES`.
- [x] 3.1 Create `src/interfaces/http/routes/matches_router.py` with `POST /matches`, `GET /matches`, `GET /matches/{id}`, `PUT /matches/{id}/stats`, and `GET /matches/{id}/stats`; `GET /matches` only accepts optional `team_id` in V1.
- [x] 3.2 Update `src/interfaces/http/routes/players_router.py` for `GET /players/{player_id}/stats` and `GET /players/{player_id}/matches` responses.
- [x] 3.3 Update `src/interfaces/http/routes/team_router.py` for `GET /teams/{team_id}/stats` and the `TEAM_HAS_MATCHES` 409 envelope.
- [x] 3.4 Wire new repositories/use cases in `src/interfaces/http/bootstrap/dependencies.py` and register `matches_router` in `src/interfaces/http/bootstrap/router_wiring.py` without touching job `stats_router` behavior.
- [x] 4.1 Add unit tests for `src/application/matches/use_cases.py` covering inaccessible teams, `winner_team_id` invariants, opaque stats replace, and no player aggregate recomputation.
- [x] 4.2 Add/extend player/team unit tests for default `players.stats`, `GET /players/{id}/stats`, and team-delete conflict mapping.
- [x] 4.3 Create `tests/integration/test_match_stats_integration.py` for create/list-by-`team_id`, get stats with participants, replace stats, player history, team summary, and `winner_team_id` result derivation.
- [x] 4.4 Extend `tests/integration/test_team_crud_integration.py` and migration bootstrap assertions to verify deleting a referenced team returns 409 `TEAM_HAS_MATCHES` after real migrations run.

## Verification
- Passed: `/tmp/opencode/back-venv311/bin/python -m pytest tests/application tests/interfaces/http`
- Passed: `/tmp/opencode/back-venv311/bin/python -m pytest tests/application/players/test_player_use_cases.py tests/application/matches/test_match_use_cases.py tests/interfaces/http/test_players_router.py tests/interfaces/http/test_team_router.py tests/interfaces/http/test_main_wiring.py`
- Skipped (environment): `/tmp/opencode/back-venv311/bin/python -m pytest tests/integration/test_player_crud_integration.py tests/integration/test_team_crud_integration.py tests/integration/test_match_stats_integration.py` because PostgreSQL at `localhost:5435` was unreachable.

## Deviations
- None — implementation matches the approved V1 scope.

## Post-Review Blocker Fixes
- [x] Reject `POST /matches` requests where `home_team_id == away_team_id` with controlled match-domain validation before persistence.
- [x] Reject `PUT /matches/{id}/stats` participant `player_id` values that are missing or owned by another user with controlled match-domain errors before repository writes.
- [x] Narrow team-delete FK conflict mapping so only `matches_*_team_id_fkey` violations become `TEAM_HAS_MATCHES`; unrelated team FK conflicts keep their original error path.

## Verification Addendum
- Passed: `/tmp/opencode/back-venv311/bin/python -m pytest tests/application/matches/test_match_use_cases.py tests/interfaces/http/test_matches_router.py tests/interfaces/http/test_main_wiring.py`
- Passed: `/tmp/opencode/back-venv311/bin/python -m pytest tests/application/team/test_use_cases.py tests/infrastructure/team/test_postgres_team_repository.py tests/interfaces/http/test_team_router.py`

## Commit Blocker Cleanup
- [x] Resolved pytest collection basename collision by packaging the affected `tests/application/...` directories so `team/test_use_cases.py` and `video/test_use_cases.py` import with unique module paths.
- [x] Aligned new JSONB writes in `src/infrastructure/players/postgres_player_repository.py` and `src/infrastructure/matches/postgres_repository.py` with the repo's explicit serialization + `::jsonb` cast pattern.

## Verification Addendum 2
- Passed: `/tmp/opencode/back-venv311/bin/python -m pytest tests/application tests/infrastructure tests/interfaces/http`

## Workload / PR Boundary
- Mode: size:exception
- Current work unit: full `match-stats-foundation`
- Boundary: schema + application + HTTP wiring + tests for the match stats V1 foundation in one batch
- Estimated review budget impact: above the 400-line default budget, implemented under the maintainer-approved size exception
