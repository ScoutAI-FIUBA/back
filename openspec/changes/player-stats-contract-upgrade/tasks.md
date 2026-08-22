# Tasks: Player Stats Contract Upgrade

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 420-560 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 migration/defaults -> PR 2 repository/tests |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Canonical defaults and DB backfill | PR 1 | Base = main; include domain/use-case + migration tests |
| 2 | Read normalization and endpoint regressions | PR 2 | Base = PR 1 branch if chained; verify no legacy keys leak |

## Phase 1: Foundation

- [x] 1.1 Update `src/domain/players/entities.py` to define the canonical nested stats builder/default shape and widen `Player.stats` typing for nested JSON values.
- [x] 1.2 Update `src/application/players/use_cases.py` so `CreatePlayerUseCase` still seeds new players from the canonical builder with all numeric fields at `0`.
- [x] 1.3 Update `tests/application/players/test_player_use_cases.py` to assert the exact canonical default shape and persisted-stats-only behavior from the spec scenarios.

## Phase 2: Migration and Repository Normalization

- [x] 2.1 Create `src/infrastructure/players/migrations/003_player_stats_contract_upgrade.sql` to set the new JSONB default and backfill flat or partial rows into the canonical nested shape.
- [x] 2.2 Preserve legacy values in migration mapping: keep `games_played`, move `wins/losses` into `record`, map flat counters into `{stat}.total`, and zero-fill unmapped shooting sections.
- [x] 2.3 Add a private canonicalization helper in `src/infrastructure/players/postgres_player_repository.py` and use it from `_row_to_player()` plus create-return reads.
- [x] 2.4 Ensure repository normalization accepts `NULL`, legacy flat, partial nested, and canonical rows, always returning canonical JSON without top-level legacy stat keys.

## Phase 3: Repository and API Verification

- [x] 3.1 Expand `tests/infrastructure/players/test_postgres_player_repository.py` to verify canonical JSONB serialization on create and normalization of legacy/partial rows on read.
- [x] 3.2 Update `tests/interfaces/http/test_players_router.py` to assert `GET /players/{player_id}/stats` returns nested `record` and shooting sections, and omits flat `wins`, `losses`, and scalar stat keys.
- [x] 3.3 Update `tests/integration/test_match_stats_integration.py` to verify live player stats stay canonical before and after match stats writes, without changing matches behavior.

## Phase 4: Rollout Safety

- [x] 4.1 Verify task coverage against spec scenarios for canonical defaults, safe legacy backfill, mixed-shape read protection, and persisted-only endpoint semantics.
- [x] 4.2 Document in `openspec/changes/player-stats-contract-upgrade/tasks.md` during apply whether the repository normalization guard remains as permanent defensive mapping or is removed after rollout validation.

## Apply Notes

- Repository normalization guard decision: keep it as a permanent defensive mapping. The migration rewrites stored rows, but the guard prevents stale seeds or manual SQL writes from leaking mixed legacy/new shapes through API reads.
