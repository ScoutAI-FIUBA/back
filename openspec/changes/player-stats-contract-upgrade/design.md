# Design: Player Stats Contract Upgrade

## Technical Approach

Upgrade `players.stats` with one canonical nested contract across domain defaults, persisted JSONB, repository mapping, and API reads. Implementation stays inside the player boundary: a new manual SQL migration rewrites legacy flat rows and sets the new default, while player repository mapping adds a narrow canonicalization guard so `GET /players/{player_id}/stats` never emits mixed shapes during rollout.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice / Rationale |
|---|---|---|---|
| Canonical source | DB-only backfill; DB + mapper guard | DB-only is simpler but unsafe if old fixture/manual rows survive | Use migration as primary conversion plus repository canonicalization. This keeps steady-state storage canonical and protects reads immediately. |
| Where to define defaults | SQL only; domain + SQL | SQL only would leave new app-created players inconsistent before insert/read | Define one Python builder in `src/domain/players/entities.py` and mirror it in migration SQL so create flow and DB defaults match. |
| Scope of upgrade | Recompute from matches; reshape existing stats only | Recompute is broader and touches excluded match behavior | Reshape only existing `players.stats`. Leave `matches.stats` and `match_participants` untouched. |

## Data Flow

    CreatePlayerUseCase
          │ build_empty_player_stats()
          ▼
    PostgresPlayerRepository.create ──→ players.stats JSONB
          ▲                                 │
          │ canonicalize on read           │ migration 003 rewrites legacy rows
          └──────── GET /players/{id}/stats ◀┘

Legacy flat rows are mapped as follows: `games_played` stays top-level, `wins/losses` move to `record`, existing scalar counters populate `{stat}.total`, all `per_game`, shooting totals, attempts, and percentages default to `0`. Migration SQL and repository normalization share one coercion policy: JSON numbers truncate toward `0`, booleans coerce to `1`/`0`, integer strings (after trimming) coerce to integers, and all other values normalize to `0`. Canonical output keys remain `two_point` and `three_point`, while the read/migration guard may absorb plural near-miss input keys from stale manual rows.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `openspec/changes/player-stats-contract-upgrade/design.md` | Create | Implementation design for this change |
| `src/domain/players/entities.py` | Modify | Replace flat `EMPTY_PLAYER_STATS` with canonical nested builder/constants; widen `stats` typing to nested JSON values |
| `src/application/players/use_cases.py` | Modify | Keep create flow aligned by using the new canonical builder unchanged |
| `src/infrastructure/players/migrations/003_player_stats_contract_upgrade.sql` | Create | Backfill legacy rows, zero-fill missing sections, set new JSONB default |
| `src/infrastructure/players/postgres_player_repository.py` | Modify | Add private canonicalization helper used by `_row_to_player()` and create-return reads |
| `tests/application/players/test_player_use_cases.py` | Modify | Assert exact canonical default and nested value preservation |
| `tests/infrastructure/players/test_postgres_player_repository.py` | Modify | Assert serialized canonical JSON and legacy-row normalization on read |
| `tests/interfaces/http/test_players_router.py` | Modify | Assert nested API payload and absence of legacy top-level keys |
| `tests/integration/test_match_stats_integration.py` | Modify | Assert live `/players/{id}/stats` canonical contract without changing match behavior |

## Interfaces / Contracts

```python
PlayerStats = {
    "games_played": 0,
    "record": {"wins": 0, "losses": 0},
    "points": {"total": 0, "per_game": 0},
    "rebounds": {"total": 0, "per_game": 0},
    "assists": {"total": 0, "per_game": 0},
    "steals": {"total": 0, "per_game": 0},
    "blocks": {"total": 0, "per_game": 0},
    "turnovers": {"total": 0, "per_game": 0},
    "field_goals": {"made_total": 0, "attempted_total": 0, "per_game": {"made": 0, "attempted": 0}, "percentage": 0},
    "two_point": {"made_total": 0, "attempted_total": 0, "per_game": {"made": 0, "attempted": 0}, "percentage": 0},
    "three_point": {"made_total": 0, "attempted_total": 0, "per_game": {"made": 0, "attempted": 0}, "percentage": 0},
    "free_throws": {"made_total": 0, "attempted_total": 0, "per_game": {"made": 0, "attempted": 0}, "percentage": 0},
}
```

Repository helper contract: accept `None`, canonical rows, legacy flat rows, or partially upgraded rows; always return the full canonical shape with no top-level legacy stat keys.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Canonical empty stats for new players | Update use-case tests to compare full nested payload |
| Unit | Legacy/partial repository reads normalize correctly | Add repository tests with flat and partial `stats` rows |
| Integration | Player stats endpoint returns only canonical shape | Update HTTP/integration assertions to check nested keys and missing legacy keys |
| E2E | Not applicable | Existing integration stack is sufficient for this change |

## Migration / Rollout

Add `003_player_stats_contract_upgrade.sql` after `002_player_stats_foundation.sql`. In one migration: `ALTER COLUMN stats SET DEFAULT` to the canonical JSON, `UPDATE players SET stats = ...` using `COALESCE` from legacy keys and existing nested values, and preserve already canonical rows by overlaying onto the canonical empty object. The repository canonicalization guard remains in place so responses stay canonical even if a stale seeded row bypasses migration. No feature flag; rollout is safe once migration and app ship together.

## Open Questions

- [ ] Should the temporary repository canonicalization guard remain permanently as defensive mapping, or be removed after one release once all environments are verified?
