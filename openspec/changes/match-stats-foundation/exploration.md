## Exploration: match-stats-foundation

### Current State
The backend is organized by bounded module under `src/domain`, `src/application`, `src/infrastructure`, and `src/interfaces/http`, with FastAPI routes wired centrally through `build_http_dependencies()` and `wire_routers()`. Persistence is raw SQL over psycopg, with additive/idempotent SQL migrations spread by module and executed in a fixed order by `scripts/apply_migrations.py`.

Today, `players` already support owner scoping, optional `team_id`, and small additive schema evolution (`jersey_number`) through dedicated migrations. Existing `stats` endpoints are job-analysis readers (`/jobs/{job_id}/stats`, `/jobs/{job_id}/court-positions`) backed by processing artifacts, not persisted match records, so the new basketball match/statistics foundation should be introduced as a separate module rather than extending the current job stats path.

### Affected Areas
- `scripts/apply_migrations.py` — migration order must include any new matches migration directory, otherwise local/dev/CI schemas drift.
- `tests/integration/test_player_crud_integration.py` — hardcoded migration list would miss new matches migrations unless updated.
- `tests/integration/test_video_management_integration.py` — same migration bootstrap pattern; likely needs the new directory.
- `tests/integration/test_clip_collections_integration.py` — same migration bootstrap pattern; likely needs the new directory.
- `src/infrastructure/auth/migrations/003_players_foundation.sql` — current base `players` table definition shows the starting schema that later additive player changes build on.
- `src/infrastructure/players/migrations/001_player_jersey_number.sql` — best precedent for adding `players.stats` additively without rewriting the foundation migration.
- `src/infrastructure/ownership/migrations/001_owner_scoping.sql` — owner scoping is an established persistence rule that new `matches` records should follow.
- `src/infrastructure/team/migrations/001_team_foundation.sql` — likely FK target for `home_team_id` and `away_team_id`.
- `src/infrastructure/video/migrations/001_video_management_foundation.sql` — `video_players` is the closest existing pattern for a lightweight relation table; useful precedent for `match_participants`.
- `src/application/players/ports.py` and `src/application/players/use_cases.py` — player-facing stats retrieval will need new ports/use cases without changing current CRUD semantics.
- `src/interfaces/http/bootstrap/dependencies.py` — new repositories/use cases must be constructed here.
- `src/interfaces/http/bootstrap/router_wiring.py` — new match/stat routes must be registered here.
- `src/interfaces/http/routes/stats_router.py` — naming collision risk: current "stats" router is job-oriented, not persisted-match-oriented.

### Approaches
1. **Dedicated matches module with opaque JSONB stats** — Add a new `matches` bounded context (`domain/application/infrastructure/interfaces`) plus a small participant table and keep `matches.stats` as opaque JSONB in V1.
   - Pros: Cleanly matches the current hexagonal/module layout; avoids coupling persisted matches to processing-job stats; supports partial roster coverage by making participant-to-player linkage optional; keeps V1 aligned with additive migrations and undefined final JSON shape.
   - Cons: Introduces several new files and dependency wiring points; player/team stats endpoints must be carefully defined as retrieval/filtering, not aggregate recomputation.
   - Effort: Medium

2. **Reuse the existing stats/jobs module for persisted matches** — Store match rows but expose them through the current stats router/use-case area.
   - Pros: Fewer top-level modules at first glance; may appear faster because `stats` naming already exists.
   - Cons: Wrong abstraction boundary: current stats depend on processing jobs and artifact readers, not relational match storage; increases confusion between computed job outputs and persisted match documents; makes future JSON-to-player mapping harder to separate.
   - Effort: Medium-High

### Recommendation
Use a **dedicated matches module with opaque JSONB stats**.

That fits the current architecture BEST: a new bounded context for persisted basketball matches, separate from the existing processing/job stats flow. The migration strategy should stay additive: add `players.stats` in a new player migration, add a new matches migration directory for `matches` plus `match_participants`, and update migration runners/tests to include that directory.

For API boundaries, V1 should stay intentionally narrow:
- create a match record;
- get one match's stored stats payload;
- list/filter match stats by player via `match_participants.player_id`;
- list/filter match stats by team via `matches.home_team_id` / `matches.away_team_id`.

Do **not** define recomputation semantics or JSON-to-player mapping in this phase. Because `matches.stats` shape is still open, the safest V1 contract is storage/retrieval of an opaque JSON document plus relational filtering through teams and participants.

### Risks
- The current integration test bootstrap duplicates migration directory lists; adding a new matches migration directory without updating those helpers will cause false-green unit tests and broken integration environments.
- `stats` is already a loaded term in the codebase for job-derived analytics. Reusing that module name for persisted matches will create architectural confusion and maintenance debt.
- `players.stats` needs a fixed initialized JSONB shape, but `matches.stats` does not yet. Mixing those concerns could tempt premature aggregate design; V1 should keep player aggregates initialized but unrecomputed.
- Partial roster coverage means participant rows cannot require a local `players` match. If the schema accidentally makes `player_id` mandatory, V1 will fail valid real-world imports.
- Team ownership validation for match creation must be explicit. If `home_team_id` and `away_team_id` both reference local teams, existing ownership checks can be reused; if one side may be external later, the current schema assumptions will need revision.
- `description` is intentionally free text and `match_date` is the played date. Tight validation or inferred semantics here would create accidental scope creep.

### Ready for Proposal
Yes — the change is ready for proposal if the next phase treats V1 as **schema foundation + basic retrieval endpoints only**, with `matches.stats` kept opaque and aggregate recomputation / JSON-to-player mapping explicitly deferred.
