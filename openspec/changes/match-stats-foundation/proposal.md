# Proposal: Match Stats Foundation

## Intent
- Add a durable match record model so owners can store played matches and later attach pipeline output without coupling to job artifacts.
- Create a safe V1 foundation for team/player stat retrieval while preserving existing data and avoiding premature aggregate logic.

## Scope

### In Scope
- Add additive migrations for `players.stats`, `matches` (including nullable `winner_team_id`), and owner-scoped `match_participants`.
- Support private match creation with existing home/away teams, played date, free-text description, and later stats attach/replace.
- Expose V1 read endpoints for match stats, global player stats, player match participation history, and team results (played, wins, losses, match results) derived from relational fields.
- Prevent deletion of teams that already participate in persisted matches and return HTTP 409 with a stable error contract.

### Out of Scope
- Pipeline JSON-to-player mapping, participant resolution rules, and player aggregate recomputation.
- Unknown/external teams, shared ownership, or a final enforced `matches.stats` schema.

## Capabilities

### New Capabilities
- `match-records`: owner-private match lifecycle, metadata, and participant detection storage.
- `match-stats-query`: opaque match stats attach/retrieve flows plus match/player/team stat reads and player participation-history reads.
- `player-stats-foundation`: fixed initialized `players.stats` structure exposed globally in V1.

### Modified Capabilities
- None.

## Approach
- Add a dedicated matches module, not the existing job-stats path.
- Keep `matches.stats` nullable/opaque in V1; require explicit attach/replace after match creation.
- Add `winner_team_id UUID NULL`, leave it unset at match creation, and use it as the authoritative V1 result source when later pipeline processing determines the winner.
- Use relational filters (`owner_user_id`, team IDs, nullable `player_id`, `winner_team_id`) for retrieval while leaving aggregate recomputation and payload parsing deferred.
- Treat migration-runner updates as explicit implementation work because migration directories are registered in multiple bootstraps.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `scripts/apply_migrations.py` | Modified | Register new matches migrations |
| `src/infrastructure/players/migrations/` | Modified | Add `players.stats` migration |
| `src/infrastructure/matches/` | New | Match and participant persistence |
| `src/application/players/`, `src/application/matches/` | Modified/New | V1 query and lifecycle use cases |
| `src/interfaces/http/bootstrap/`, `src/interfaces/http/routes/` | Modified | Wire match and stats endpoints |
| `tests/integration/test_player_crud_integration.py` | Modified | Include new matches migration directory |
| `tests/integration/test_video_management_integration.py` | Modified | Include new matches migration directory |
| `tests/integration/test_clip_collections_integration.py` | Modified | Include new matches migration directory |
| `tests/integration/test_team_crud_integration.py` | Modified | Include new matches migration directory for delete-conflict coverage |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Stats semantics drift before JSON shape is defined | Med | Keep payload opaque and defer mapping rules |
| Missing migration registration breaks env parity | High | Update all migration bootstraps together |
| Participant linkage assumptions block imports | Med | Keep local player link nullable |

## Rollback Plan
- Revert router wiring and new module usage, then roll back new tables/column with a dedicated down migration or restore point before deployment.

## Dependencies
- Existing owner/team validation rules and additive migration workflow.

## Success Criteria
- [ ] Owners can create a private match with existing teams before stats exist.
- [ ] Stats can be attached/replaced later and retrieved by match, player, and team scopes without JSON-to-player mapping or aggregate recomputation.
- [ ] Player responses expose global player stats, and owners can query the matches in which a known player participated.
- [ ] Team responses return played/wins/losses/results from relational winner data, not opaque stats parsing.
- [ ] Deleting a team referenced by persisted matches returns HTTP 409 with `TEAM_HAS_MATCHES`.
