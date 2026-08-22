# Apply Progress: Player Stats Contract Upgrade

## Change

- Name: `player-stats-contract-upgrade`
- Mode: Standard
- Delivery mode: `size:exception` accepted under single-pr-default
- Work unit: Full change

## Completed Tasks

- [x] 1.1 Update `src/domain/players/entities.py` to define the canonical nested stats builder/default shape and widen `Player.stats` typing for nested JSON values.
- [x] 1.2 Update `src/application/players/use_cases.py` so `CreatePlayerUseCase` still seeds new players from the canonical builder with all numeric fields at `0`.
- [x] 1.3 Update `tests/application/players/test_player_use_cases.py` to assert the exact canonical default shape and persisted-stats-only behavior from the spec scenarios.
- [x] 2.1 Create `src/infrastructure/players/migrations/003_player_stats_contract_upgrade.sql` to set the new JSONB default and backfill flat or partial rows into the canonical nested shape.
- [x] 2.2 Preserve legacy values in migration mapping: keep `games_played`, move `wins/losses` into `record`, map flat counters into `{stat}.total`, and zero-fill unmapped shooting sections.
- [x] 2.3 Add a private canonicalization helper in `src/infrastructure/players/postgres_player_repository.py` and use it from `_row_to_player()` plus create-return reads.
- [x] 2.4 Ensure repository normalization accepts `NULL`, legacy flat, partial nested, and canonical rows, always returning canonical JSON without top-level legacy stat keys.
- [x] 3.1 Expand `tests/infrastructure/players/test_postgres_player_repository.py` to verify canonical JSONB serialization on create and normalization of legacy/partial rows on read.
- [x] 3.2 Update `tests/interfaces/http/test_players_router.py` to assert `GET /players/{player_id}/stats` returns nested `record` and shooting sections, and omits flat `wins`, `losses`, and scalar stat keys.
- [x] 3.3 Update `tests/integration/test_match_stats_integration.py` to verify live player stats stay canonical before and after match stats writes, without changing matches behavior.
- [x] 4.1 Verify task coverage against spec scenarios for canonical defaults, safe legacy backfill, mixed-shape read protection, and persisted-only endpoint semantics.
- [x] 4.2 Document in `openspec/changes/player-stats-contract-upgrade/tasks.md` during apply whether the repository normalization guard remains as permanent defensive mapping or is removed after rollout validation.

## Verification

- Passed: `"/tmp/opencode/back-venv311/bin/pytest" tests/application/players/test_player_use_cases.py tests/infrastructure/players/test_postgres_player_repository.py tests/interfaces/http/test_players_router.py`
- Result: `27 passed`
- Deferred: `tests/integration/test_match_stats_integration.py` now includes a mixed-type migration regression, but it still requires `DATABASE_URL` and was not runnable in the local non-DB executor environment.

## Design Alignment

- Domain defaults and repository normalization now share the canonical nested contract.
- Migration and runtime normalization now share the same coercion policy: numbers truncate toward `0`, booleans map to `1`/`0`, trimmed integer strings are preserved, and other values normalize to `0`.
- Canonical output keys remain `two_point` and `three_point`; plural near-miss input keys are absorbed during normalization/backfill and never leak to responses.
- Repository normalization guard remains permanent as defensive mapping for stale or manually seeded rows.

## Remaining Tasks

- None.
