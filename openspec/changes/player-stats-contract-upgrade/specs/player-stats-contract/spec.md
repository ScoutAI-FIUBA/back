# Player Stats Contract Specification

## Purpose

Define the canonical persisted and returned `players.stats` contract for player aggregates.

## Requirements

### Requirement: Persist Canonical Nested Player Stats

The system MUST persist and return `players.stats` using this canonical JSON shape. Every numeric value MUST initialize to `0`.

```json
{
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
  "free_throws": {"made_total": 0, "attempted_total": 0, "per_game": {"made": 0, "attempted": 0}, "percentage": 0}
}
```

#### Scenario: New player receives canonical defaults

- GIVEN a player is created after the upgrade
- WHEN the player is persisted
- THEN `players.stats` matches the canonical nested shape exactly
- AND every numeric field equals `0`

#### Scenario: Missing nested sections are zero-filled

- GIVEN a player stats payload is missing one or more canonical nested sections
- WHEN that payload is stored or returned
- THEN the missing section is present in the canonical shape with all numeric values set to `0`

### Requirement: Upgrade Legacy Flat Player Stats Safely

The system MUST backfill legacy flat `players.stats` payloads into the canonical shape before they can be observed through API responses. `wins` and `losses` SHALL move under `record`, legacy aggregate counters SHALL preserve their values under each `{stat}.total`, and canonical fields with no historical source value MUST remain `0`.

Numeric coercion for legacy/manual rows MUST be consistent in migration and runtime normalization: JSON numbers truncate toward `0`, booleans coerce to `1`/`0`, integer strings (after trimming whitespace) coerce to integers, and every other value normalizes to `0`. Canonical output keys remain `two_point` and `three_point`; plural near-miss input keys MUST NOT leak to output.

#### Scenario: Flat legacy payload is backfilled without losing values

- GIVEN a stored legacy payload with flat keys such as `games_played`, `wins`, `losses`, and `points`
- WHEN the upgrade migration runs
- THEN the stored payload is rewritten to the canonical nested shape
- AND the legacy values are preserved in their mapped canonical fields

#### Scenario: Mixed old and new shapes never leak through reads

- GIVEN an environment still contains a legacy or partially upgraded player stats row
- WHEN a client requests that player's stats
- THEN the response contains only the canonical nested shape
- AND no legacy top-level `wins`, `losses`, or flat scalar stat keys are exposed

### Requirement: Preserve Existing Player Stats Endpoint Semantics

The existing player stats endpoint MUST keep the same owner-scoped and persisted-stats-only behavior, and SHALL change only the returned `stats` JSON shape.

#### Scenario: Endpoint returns richer nested stats contract

- GIVEN an owner requests `GET /players/{player_id}/stats`
- WHEN the player exists
- THEN the endpoint returns the player's persisted canonical nested stats payload

#### Scenario: Endpoint does not recalculate from match data

- GIVEN related `matches.stats` or `match_participants` data exists
- WHEN the owner requests player stats
- THEN the response is based only on persisted `players.stats`
- AND match data remains unchanged by this capability
