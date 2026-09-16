## Exploration: player-stats-contract-upgrade

### Current State
`players.stats` is currently a flat fixed JSONB object initialized in both the domain and the database with only aggregate counters (`games_played`, `wins`, `losses`, `points`, `rebounds`, `assists`, `steals`, `blocks`, `turnovers`). The create flow always writes that shape, the repository returns the JSONB payload as-is, and `GET /players/{player_id}/stats` exposes it without transformation.

The richer basketball stat vocabulary already exists elsewhere in the codebase, but only in the job-analysis box score path under `src/domain/stats/entities.py`, where shooting stats are modeled with a broader contract (`field_goals_*`, `two_point_*`, `three_point_*`, percentages, and `by_zone`). No in-repo source of truth currently defines the new canonical persisted `players.stats` payload, and no compatibility shim exists if rows keep the old flat shape.

### Affected Areas
- `src/domain/players/entities.py` — current `EMPTY_PLAYER_STATS` and `build_empty_player_stats()` define the old flat default used everywhere.
- `src/application/players/use_cases.py` — create flow injects the domain default, so the new contract must start here for new players.
- `src/infrastructure/players/migrations/002_player_stats_foundation.sql` — current additive migration both backfills and sets the old JSONB default; a follow-up migration is needed to preserve existing data while upgrading shape.
- `src/infrastructure/players/postgres_player_repository.py` — repository reads/writes `stats` opaquely, so migration correctness directly determines API consistency.
- `src/interfaces/http/routes/players_router.py` — `/players/{player_id}/stats` returns the stored payload as-is; richer nested responses will appear here without extra mapping.
- `tests/application/players/test_player_use_cases.py` — asserts the current `EMPTY_PLAYER_STATS` structure and point overrides.
- `tests/interfaces/http/test_players_router.py` — asserts the old flat stats payload shape on the player stats endpoint.
- `tests/integration/test_match_stats_integration.py` — currently checks the old `games_played` flat key through the live HTTP stack.
- `src/domain/stats/entities.py` — best in-repo precedent for the richer basketball stat vocabulary the new canonical payload likely needs to mirror or align with.

### Approaches
1. **Migration-first full contract replacement** — Add a new additive migration that rewrites every existing `players.stats` value into the canonical nested structure, update domain defaults to the same shape, and update tests to assert only the richer contract.
   - Pros: Single canonical shape in storage and API; no long-term legacy branching in repository/router code; simplest steady state.
   - Cons: Migration must carefully map old flat counters into the new nested structure; if any row escapes conversion, the API can still return mixed shapes because reads are opaque.
   - Effort: Medium

2. **Migration plus temporary read-normalization safety net** — Do the same migration, but also normalize legacy rows in repository/domain reads for one release window so mixed-shape records still serialize as the canonical contract.
   - Pros: Safer rollout if some environments contain partially migrated or manually seeded legacy rows; protects the endpoint contract from bad historical data.
   - Cons: Adds transitional complexity and a second place that knows the old-to-new mapping; easy to forget to remove later.
   - Effort: Medium-High

### Recommendation
Use **Approach 2** for the change, but keep the normalization layer intentionally small and local to player stats mapping.

Why: the repository currently returns JSONB exactly as stored, and the scope explicitly asks for additive-safe migration behavior while preserving existing data. A new migration should be the primary conversion mechanism, but a narrow normalization fallback in player mapping is the safest way to guarantee that `/players/{id}/stats` always returns the richer nested contract even if older flat rows survive in some environment, fixture, or manual seed.

The proposal/spec should also pin the exact canonical JSON example because no OpenSpec source-of-truth currently exists in-repo for that richer persisted shape.

### Risks
- The exact canonical nested `players.stats` contract is not defined anywhere in the repo today; implementing without first pinning the JSON example risks mismatched defaults, backfill logic, and tests.
- Existing flat counters like `points`, `rebounds`, and `assists` likely map cleanly, but new nested shooting sections may not have historical source values; those fields will need explicit zero/default semantics.
- Because `postgres_player_repository.py` reads `stats` opaquely, any missed backfill leaves the API returning inconsistent shapes immediately.
- Tests currently assert individual flat keys (`games_played`, `points`), so broad fixture updates are required across unit, router, and integration coverage.
- `matches.stats` and `match_participants` must remain untouched; proposal/spec wording has to prevent accidental scope creep into recomputation from persisted match data.

### Ready for Proposal
Yes — this is ready for proposal if the next phase first records the exact canonical JSON contract, then scopes implementation to: new domain defaults, an additive migration/backfill from flat-to-canonical player stats, an optional repository normalization safety net, and test updates proving the old flat shape is no longer exposed.
