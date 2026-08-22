# Design: Match Stats Foundation

## Technical Approach

Add a dedicated `matches` module that follows the repo's existing split (`domain` → `application` → `infrastructure` → `interfaces/http`) and keeps V1 storage simple: relational match metadata (`home_team_id`, `away_team_id`, nullable `winner_team_id`) plus opaque `matches.stats` JSONB. This implements `match-records`, `match-stats-query`, and `player-stats-foundation` without coupling to the existing job-artifact stats flow.

## Architecture Decisions

| Decision | Options | Choice / Rationale |
|---|---|---|
| Match boundary | Reuse `stats` job module / new `matches` module | **New `matches` module**. Current `stats` code reads job artifacts, not relational data; mixing them would blur ownership and retrieval rules. |
| Player aggregate init | DB default only / explicit app init + DB default | **Both**. Add `players.stats JSONB NOT NULL DEFAULT ...` and backfill existing rows; `CreatePlayerUseCase` also sets the same `EMPTY_PLAYER_STATS` constant so domain/repository/router always carry a concrete value. |
| Match outcome source | Parse `matches.stats` / store winner relationally | **Store `winner_team_id UUID NULL` on `matches`**. V1 team results use that field, not opaque JSON parsing; `NULL` keeps outcome pending until later pipeline processing. |
| Team/player delete semantics | Cascade / restrict / nullify | **`matches.home_team_id` and `away_team_id` use `ON DELETE RESTRICT`** to preserve historical results, and the HTTP layer maps that conflict to **409 `TEAM_HAS_MATCHES`**. **`match_participants.player_id` uses `ON DELETE SET NULL`** so participant evidence survives player deletion. **`match_participants.match_id` uses `ON DELETE CASCADE`** so replacing or deleting a match removes child rows safely. |
| Ownership enforcement | App-only / DB + app | **Both**. `matches` stores `owner_user_id`; `match_participants` also stores `owner_user_id` and references `(match_id, owner_user_id)` on `matches` to prevent cross-owner rows. Use cases still validate `teams.is_owned_by(...)` on create/query. |

## Data Flow

`POST /matches` → `matches_router` → `CreateMatchUseCase` → `PostgresMatchRepository`
`PUT /matches/{id}/stats` → replace `matches.stats` + delete/insert `match_participants`
`Pipeline result processing` → set `matches.winner_team_id` when winner becomes known
`GET /matches/{id}/stats` → load scoped match + participants
`GET /players/{id}/stats` → read `players.stats`
`GET /players/{id}/matches` / `GET /teams/{id}/stats` → query `match_participants` + `matches` and derive team results from `winner_team_id`

    HTTP Router -> Use Case -> Repository -> Postgres
         |                           |
         +-> ownership checks <------+

## File Changes

| File | Action | Description |
|---|---|---|
| `src/infrastructure/matches/migrations/001_match_stats_foundation.sql` | Create | Add `matches`, `match_participants`, nullable `winner_team_id`, indexes, and composite ownership constraint. |
| `src/domain/matches/entities.py` | Create | Match and participant read models. |
| `src/application/matches/{ports,use_cases,errors}.py` | Create | CRUD/query contracts for matches and team/player participation reads. |
| `src/infrastructure/matches/postgres_repository.py` | Create | Raw SQL adapter for match create/list/get/stats replace/query flows. |
| `src/interfaces/http/routes/matches_router.py` | Create | `create/list/get match`, `attach/replace match stats`, `get match stats`. |
| `src/interfaces/http/bootstrap/{dependencies,router_wiring}.py` | Modify | Construct repository/use cases and register the new router. |
| `src/domain/players/entities.py` | Modify | Add `stats: dict[str, int] | dict[str, object]`. |
| `src/application/players/{ports,use_cases}.py` | Modify | Add `get_by_id`/stats query use case and initialize stats on create. |
| `src/infrastructure/players/postgres_player_repository.py` | Modify | Map/select/insert `players.stats`. |
| `src/interfaces/http/routes/players_router.py` | Modify | Add `GET /players/{player_id}/stats` and `GET /players/{player_id}/matches`. |
| `src/interfaces/http/routes/team_router.py` | Modify | Add `GET /teams/{team_id}/stats` and map team-delete match conflicts to 409 `TEAM_HAS_MATCHES`. |
| `scripts/apply_migrations.py` | Modify | Register `src/infrastructure/matches/migrations` in the app migration runner. |
| `tests/integration/test_player_crud_integration.py` | Modify | Register `src/infrastructure/matches/migrations` in duplicated test bootstrap. |
| `tests/integration/test_video_management_integration.py` | Modify | Register `src/infrastructure/matches/migrations` in duplicated test bootstrap. |
| `tests/integration/test_clip_collections_integration.py` | Modify | Register `src/infrastructure/matches/migrations` in duplicated test bootstrap. |
| `tests/integration/test_team_crud_integration.py` | Modify | Register `src/infrastructure/matches/migrations` so delete-conflict coverage can execute against the real schema. |

## Interfaces / Contracts

```python
EMPTY_PLAYER_STATS = {
    "games_played": 0, "wins": 0, "losses": 0,
    "points": 0, "rebounds": 0, "assists": 0,
    "steals": 0, "blocks": 0, "turnovers": 0,
}
```

`matches`: `id`, `owner_user_id`, `home_team_id`, `away_team_id`, `winner_team_id UUID NULL`, `match_date`, `description`, `stats JSONB NULL`, `created_at`, `updated_at`.

`match_participants`: `id`, `match_id`, `owner_user_id`, `player_id NULL`, `team_side ('HOME'|'AWAY')`, `display_name`, `jersey_number`, `created_at`.

Deletion error envelope follows existing app patterns:

```python
{"error": {"code": "TEAM_HAS_MATCHES", "message": "Team has persisted matches"}}
```

V1 endpoints:
- `POST /matches`, `GET /matches`, `GET /matches/{match_id}`
- `PUT /matches/{match_id}/stats`, `GET /matches/{match_id}/stats`
- `GET /players/{player_id}/stats`, `GET /players/{player_id}/matches`
- `GET /teams/{team_id}/stats`

Index plan: `matches(owner_user_id, match_date DESC, created_at DESC)`, `matches(home_team_id)`, `matches(away_team_id)`, `matches(winner_team_id)`, `match_participants(match_id)`, `match_participants(owner_user_id, player_id, match_id)`. No JSONB index in V1 because stats are opaque and not queried by shape.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Match/team/player use-case ownership rules, `winner_team_id` invariants, delete-conflict mapping, and replace semantics | New use-case tests with fake ports. |
| Integration | Migrations, owner scoping, FK behavior, 409 team delete contract, stats replace, and player/team query endpoints | New `tests/integration/test_match_stats_integration.py`; update each existing migration helper to apply matches migrations. |
| E2E | None in repo today | Not added in V1. |

## Migration / Rollout

Additive only. Backfill every existing `players` row with `EMPTY_PLAYER_STATS` and set a matching default for new inserts. No existing `matches` data needs cleanup because the table is new. Operationally, all migration bootstraps (`scripts/apply_migrations.py`, `tests/integration/test_player_crud_integration.py`, `tests/integration/test_video_management_integration.py`, `tests/integration/test_clip_collections_integration.py`, `tests/integration/test_team_crud_integration.py`) must include the new migration directory or environments will drift.

## Open Questions

- [ ] Should `GET /matches` support only optional `team_id`, or also date filters in V1?
