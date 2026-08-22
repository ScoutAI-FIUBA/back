# Proposal: Player Stats Contract Upgrade

## Intent
Upgrade `players.stats` from the current flat JSONB payload to the canonical nested basketball stats contract so all player rows and API responses expose one richer, stable shape without recalculating from match data.

## Scope

### In Scope
- Replace player stat defaults with the canonical nested structure, with every numeric field initialized to `0`.
- Backfill existing `players.stats` rows into the new shape while preserving current values and preventing mixed old/new contracts after migration.
- Keep endpoint behavior unchanged except for returning the richer nested stats payload; update automated tests accordingly.

### Out of Scope
- Recalculating player stats from matches.
- Changes to `matches.stats` or `match_participants`.
- New endpoint semantics, derived metrics, or reporting features beyond the contract upgrade.

## Capabilities

### New Capabilities
- `player-stats-contract`: Defines the canonical persisted and returned `players.stats` structure, defaults, and migration expectations.

### Modified Capabilities
- None.

## Approach
Use a migration-first upgrade backed by a small player-stats normalization safety net if needed during read/write mapping. Move `wins` and `losses` under `record`, keep naming as `made_total`, `attempted_total`, `per_game`, and `percentage`, and zero-fill sections with no historical source data.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/domain/players/entities.py` | Modified | New canonical empty player stats builder/defaults |
| `src/application/players/use_cases.py` | Modified | New players start with canonical stats |
| `src/infrastructure/players/migrations/` | Modified | Add migration to rewrite existing JSONB rows safely |
| `src/infrastructure/players/postgres_player_repository.py` | Modified | Optional narrow normalization guard for legacy rows |
| `tests/application/players/test_player_use_cases.py` | Modified | Assert canonical default shape |
| `tests/interfaces/http/test_players_router.py` | Modified | Assert richer nested response |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Missed backfill leaves mixed contracts | Med | Rewrite all rows in migration and add regression coverage |
| New nested fields lack historical values | High | Define explicit zero defaults for every numeric field |
| Scope drifts into recomputation work | Low | Spec non-goals explicitly exclude match-based recalculation |

## Rollback Plan
Revert the proposal implementation, restore the previous player stats default contract, and roll back the migration with a reverse JSON reshape for affected rows before enabling further writes.

## Dependencies
- Final canonical JSON example must be pinned in specs before implementation.

## Success Criteria
- [ ] All `players.stats` records use the canonical nested structure after migration.
- [ ] `GET /players/{player_id}/stats` returns the richer shape with no legacy flat payloads.
- [ ] Tests cover defaults, preserved migrated values, and zero-filled new fields.
