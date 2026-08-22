# Tasks: Match Stats Foundation

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 650-800 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 migrations+repos → PR 2 routes+queries+tests |
| Delivery strategy | ask-always |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Schema + repository foundation | PR 1 | Base slice; includes migration bootstraps and repository tests |
| 2 | HTTP queries + conflict contract | PR 2 | Depends on PR 1; includes router wiring and integration coverage |

## Phase 1: Foundation

- [x] 1.1 Create `src/infrastructure/matches/migrations/001_match_stats_foundation.sql` for `matches`/`match_participants`, nullable `winner_team_id`, ownership FKs, delete rules, and indexes.
- [x] 1.2 Add `src/infrastructure/players/migrations/002_player_stats_foundation.sql` to add `players.stats`, backfill existing rows, and enforce the V1 default aggregate.
- [x] 1.3 Register `src/infrastructure/matches/migrations` in `scripts/apply_migrations.py` and in `tests/integration/test_{player_crud,video_management,clip_collections,team_crud}_integration.py` bootstrap helpers.
- [x] 1.4 Add `src/domain/matches/entities.py` and extend `src/domain/players/entities.py` with the V1 stats shape used by persistence and responses.

## Phase 2: Application + Persistence

- [x] 2.1 Create `src/application/matches/{ports,use_cases,errors}.py` for create/list/get, stats replace, player-history, and team-summary flows with owner checks.
- [x] 2.2 Extend `src/application/players/{ports,use_cases}.py` so create/get flows initialize and return global `players.stats` without recomputation.
- [x] 2.3 Implement `src/infrastructure/matches/postgres_repository.py` for `POST /matches`, `GET /matches`, `GET /matches/{id}`, stats replace, participant replace, player history, and team summary queries.
- [x] 2.4 Update `src/infrastructure/players/postgres_player_repository.py` to insert/select/map `players.stats`; verify new rows and migrated rows return the same default payload.
- [x] 2.5 Update `src/infrastructure/team/postgres_repository.py` plus team application error handling to map team-delete FK conflicts to HTTP 409 `TEAM_HAS_MATCHES`.

## Phase 3: HTTP Wiring

- [x] 3.1 Create `src/interfaces/http/routes/matches_router.py` with `POST /matches`, `GET /matches`, `GET /matches/{id}`, `PUT /matches/{id}/stats`, and `GET /matches/{id}/stats`; `GET /matches` only accepts optional `team_id` in V1.
- [x] 3.2 Update `src/interfaces/http/routes/players_router.py` for `GET /players/{player_id}/stats` and `GET /players/{player_id}/matches` responses.
- [x] 3.3 Update `src/interfaces/http/routes/team_router.py` for `GET /teams/{team_id}/stats` and the `TEAM_HAS_MATCHES` 409 envelope.
- [x] 3.4 Wire new repositories/use cases in `src/interfaces/http/bootstrap/dependencies.py` and register `matches_router` in `src/interfaces/http/bootstrap/router_wiring.py` without touching job `stats_router` behavior.

## Phase 4: Verification

- [x] 4.1 Add unit tests for `src/application/matches/use_cases.py` covering inaccessible teams, `winner_team_id` invariants, opaque stats replace, and no player aggregate recomputation.
- [x] 4.2 Add/extend player/team unit tests for default `players.stats`, `GET /players/{id}/stats`, and team-delete conflict mapping.
- [x] 4.3 Create `tests/integration/test_match_stats_integration.py` for create/list-by-`team_id`, get stats with participants, replace stats, player history, team summary, and `winner_team_id` result derivation.
- [x] 4.4 Extend `tests/integration/test_team_crud_integration.py` and migration bootstrap assertions to verify deleting a referenced team returns 409 `TEAM_HAS_MATCHES` after real migrations run.
