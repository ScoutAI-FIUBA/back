## Verification Report

**Change**: match-stats-foundation
**Version**: N/A
**Mode**: Standard

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 17 |
| Tasks complete | 17 |
| Tasks incomplete | 0 |

### Build & Tests Execution
**Build**: ➖ Not run (Python service; verification used runtime tests directly)

**Tests**: ✅ 37 passed / ❌ 0 failed / ⚠️ 5 skipped
```text
Command: /tmp/opencode/back-venv311/bin/python -m pytest tests/application/matches/test_match_use_cases.py tests/application/players/test_player_use_cases.py tests/interfaces/http/test_players_router.py tests/interfaces/http/test_team_router.py tests/interfaces/http/test_main_wiring.py
Result: 37 passed in 4.32s

Command: /tmp/opencode/back-venv311/bin/python -m pytest -rs tests/integration/test_match_stats_integration.py tests/integration/test_team_crud_integration.py
Result: 5 skipped in 0.66s
Skip reason: Postgres not reachable for integration tests: connection to 127.0.0.1:5435 failed: Connection refused
```

**Coverage**: ➖ Not available

### Spec Compliance Matrix
| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Match Records — Create Owner-Private Match Records | Create a match with existing teams | `tests/integration/test_match_stats_integration.py::test_match_stats_foundation_flow` | ❌ UNTESTED |
| Match Records — Create Owner-Private Match Records | Reject unknown or inaccessible teams | `tests/application/matches/test_match_use_cases.py::TestMatchUseCases::test_create_match_rejects_inaccessible_team` | ✅ COMPLIANT |
| Match Records — Match Metadata Rules | Create without stats payload | `tests/integration/test_match_stats_integration.py::test_match_stats_foundation_flow` | ❌ UNTESTED |
| Match Records — Match Metadata Rules | Preserve free-text description | `tests/integration/test_match_stats_integration.py::test_match_stats_foundation_flow` | ❌ UNTESTED |
| Match Records — Match Metadata Rules | Persist only valid winners | `tests/application/matches/test_match_use_cases.py::TestMatchUseCases::test_replace_stats_rejects_invalid_winner_team` | ⚠️ PARTIAL |
| Match Records — Protect Teams Referenced By Matches | Reject deletion of a referenced team | `tests/interfaces/http/test_team_router.py::TestTeamRouter::test_delete_team_maps_match_conflict_to_409_envelope`; `tests/integration/test_team_crud_integration.py::test_delete_team_with_persisted_match_returns_conflict` | ⚠️ PARTIAL |
| Match Records — Protect Teams Referenced By Matches | Allow deletion of an unreferenced team | `tests/integration/test_team_crud_integration.py::test_team_crud_happy_path` | ❌ UNTESTED |
| Match Records — Manage Lightweight Match Participants | Attach participants with mixed linkage | `tests/integration/test_match_stats_integration.py::test_match_stats_foundation_flow` | ❌ UNTESTED |
| Match Records — Manage Lightweight Match Participants | Preserve participants when player linkage is absent | `tests/integration/test_match_stats_integration.py::test_match_stats_foundation_flow` | ❌ UNTESTED |
| Match Stats Query — Attach or Replace Match Stats After Creation | Attach stats to an existing match | `tests/application/matches/test_match_use_cases.py::TestMatchUseCases::test_replace_stats_keeps_payload_opaque_without_player_recompute` | ⚠️ PARTIAL |
| Match Stats Query — Attach or Replace Match Stats After Creation | Replace existing stats payload | `tests/integration/test_match_stats_integration.py::test_match_stats_foundation_flow` | ❌ UNTESTED |
| Match Stats Query — Attach or Replace Match Stats After Creation | Do not derive player aggregates from attached stats | `tests/application/matches/test_match_use_cases.py::TestMatchUseCases::test_replace_stats_keeps_payload_opaque_without_player_recompute` | ✅ COMPLIANT |
| Match Stats Query — Return Match Stats With Participants | Read match stats and participants | `tests/integration/test_match_stats_integration.py::test_match_stats_foundation_flow` | ❌ UNTESTED |
| Match Stats Query — Return Match Stats With Participants | Read a match without stats | (none found) | ❌ UNTESTED |
| Match Stats Query — List Matches for a Known Player | List a player's participated matches | `tests/interfaces/http/test_players_router.py::TestPlayerStatsEndpoints::test_get_player_matches_returns_participation_matches`; `tests/integration/test_match_stats_integration.py::test_match_stats_foundation_flow` | ⚠️ PARTIAL |
| Match Stats Query — List Matches for a Known Player | Ignore unlinked participants for player history | (none found) | ❌ UNTESTED |
| Match Stats Query — Return Team Match Results Summary | Read team results summary | `tests/interfaces/http/test_team_router.py::TestTeamRouter::test_get_team_stats_returns_summary`; `tests/integration/test_match_stats_integration.py::test_match_stats_foundation_flow` | ⚠️ PARTIAL |
| Match Stats Query — Return Team Match Results Summary | Ignore opaque stats payload for result calculation | `tests/integration/test_match_stats_integration.py::test_match_stats_foundation_flow` | ❌ UNTESTED |
| Match Stats Query — Return Team Match Results Summary | Return empty team summary | (none found) | ❌ UNTESTED |
| Player Stats Foundation — Initialize Fixed Player Stats Aggregate | Existing player receives initialized stats | (none found) | ❌ UNTESTED |
| Player Stats Foundation — Initialize Fixed Player Stats Aggregate | New player receives initialized stats | `tests/application/players/test_player_use_cases.py`; `tests/interfaces/http/test_players_router.py::TestPlayerStatsEndpoints::test_get_player_stats_returns_global_stats_payload` | ⚠️ PARTIAL |
| Player Stats Foundation — Expose Global Player Stats Only | Read global player stats | `tests/interfaces/http/test_players_router.py::TestPlayerStatsEndpoints::test_get_player_stats_returns_global_stats_payload` | ✅ COMPLIANT |
| Player Stats Foundation — Expose Global Player Stats Only | Do not derive player stats from match payloads | `tests/application/matches/test_match_use_cases.py::TestMatchUseCases::test_replace_stats_keeps_payload_opaque_without_player_recompute` | ✅ COMPLIANT |

**Compliance summary**: 4/24 scenarios compliant, 6/24 partial, 14/24 untested.

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| Locked V1 schema | ✅ Implemented | `001_match_stats_foundation.sql` adds `matches`, `match_participants`, nullable `winner_team_id`, ownership FK, and delete rules; `002_player_stats_foundation.sql` adds/backfills `players.stats`. |
| Locked V1 endpoints | ✅ Implemented | Routes expose only `POST/GET /matches`, `GET /matches/{id}`, `PUT/GET /matches/{id}/stats`, `GET /players/{id}/stats`, `GET /players/{id}/matches`, `GET /teams/{id}/stats`. |
| `TEAM_HAS_MATCHES` contract | ✅ Implemented | Team delete catches FK conflict and maps it to HTTP 409 with code `TEAM_HAS_MATCHES`. |
| Team results derive from relational data | ✅ Implemented | `get_team_stats()` computes WIN/LOSS/PENDING from `winner_team_id`; it does not parse `matches.stats`. |
| No out-of-scope mapping/recomputation | ✅ Implemented | Match stats replacement writes opaque payload and participants only; no player aggregate update or JSON-to-player mapping exists in matches code. |

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| New dedicated matches module | ✅ Yes | Matches code is isolated under `src/application|domain|infrastructure/interfaces/http/matches`. |
| `winner_team_id` as authoritative V1 outcome source | ✅ Yes | Enforced in use case and DB check constraint; team summary reads only this relational field. |
| Team delete restriction + `TEAM_HAS_MATCHES` | ✅ Yes | SQL uses `ON DELETE RESTRICT`; application maps FK conflict to 409. |
| Participant linkage nullable, retained independently | ✅ Yes | `match_participants.player_id` is nullable with `ON DELETE SET NULL`. |
| `GET /matches` only optional `team_id` in V1 | ✅ Yes | Router signature only accepts `team_id`; no extra filters were introduced. |
| No V1 aggregate recomputation or payload parsing | ✅ Yes | Repository never queries inside JSON payload and no recomputation path was added. |

### Issues Found
**CRITICAL**:
- PostgreSQL-backed integration evidence is unavailable because the test database at `localhost:5435` was unreachable. This blocks runtime proof of additive migrations, owner-scoped persistence, FK delete behavior, participant persistence, and end-to-end API behavior against the real schema.
- Required spec scenarios that depend on real DB execution remain `UNTESTED`, so the change cannot be marked archive-ready yet.

**WARNING**:
- Several scenarios are only partially covered through mocked/unit runtime tests (for example `TEAM_HAS_MATCHES`, winner validation, player-match/team-summary transports) rather than through real repository/database execution.

**SUGGESTION**:
- Bring up PostgreSQL on `localhost:5435` and rerun `tests/integration/test_match_stats_integration.py tests/integration/test_team_crud_integration.py` before archive or merge.
- Add explicit runtime tests for currently uncovered scenarios such as `GET /matches/{id}/stats` with `stats = null`, empty team summary, and existing-player migration backfill verification.

### Verdict
FAIL
Implementation statically aligns with the locked V1 scope, but full SDD verification fails because DB-backed scenarios required to prove schema and end-to-end behavior were skipped.
