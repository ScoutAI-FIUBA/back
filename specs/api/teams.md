# Teams API Contract

## Base
- Prefix: `/teams`

## Entity

```json
{
  "id": "uuid",
  "name": "Team Alpha",
  "short_name": "TAL",
  "city": "Buenos Aires",
  "country": "Argentina",
  "created_at": "2026-05-25T12:34:56+00:00",
  "is_own": false
}
```

- `is_own` marks the user's own teams ("Mi equipo"). Existing teams are `false`. Videos and analysis stay allowed for every team.

## Endpoints

### POST /teams
- Body:

```json
{
  "name": "Team Alpha",
  "short_name": "TAL",
  "city": "Buenos Aires",
  "country": "Argentina",
  "is_own": true
}
```

- `is_own` is optional and defaults to `false`.

- 201 response:

```json
{
  "team": {
    "id": "uuid",
    "name": "Team Alpha",
    "short_name": "TAL",
    "city": "Buenos Aires",
    "country": "Argentina",
    "created_at": "2026-05-25T12:34:56+00:00",
    "is_own": true
  }
}
```

- Status codes: `201`, `422`.

### GET /teams
- 200 response:

```json
{
  "teams": [
    {
      "id": "uuid",
      "name": "Team Alpha",
      "short_name": "TAL",
      "city": "Buenos Aires",
      "country": "Argentina",
      "created_at": "2026-05-25T12:34:56+00:00",
      "is_own": true
    }
  ]
}
```

- Ordering: own teams first (`is_own DESC`), then newest first (`created_at DESC`).

- Status codes: `200`.

### PUT /teams/{team_id}
- Path param: `team_id` (UUID)
- Body:

```json
{
  "name": "Updated Team",
  "short_name": "UPD",
  "city": "Cordoba",
  "country": "Argentina",
  "is_own": true
}
```

- PUT replaces `name`, `short_name`, `city` and `country`. `is_own` is optional: omitted or `null` keeps the stored value, `true`/`false` changes it.

- 200 response:

```json
{
  "team": {
    "id": "uuid",
    "name": "Updated Team",
    "short_name": "UPD",
    "city": "Cordoba",
    "country": "Argentina",
    "created_at": "2026-05-25T12:34:56+00:00",
    "is_own": true
  }
}
```

- 404 response:

```json
{ "detail": "Team not found" }
```

- Status codes: `200`, `404`, `422`.

### DELETE /teams/{team_id}
- Path param: `team_id` (UUID)
- 204 response: no content.
- 404 response:

```json
{ "detail": "Team not found" }
```

- Status codes: `204`, `404`, `422`.

## Persistence
- Migration: `src/infrastructure/team/migrations/001_team_foundation.sql`.
- Creates `teams` table with required non-null fields:
  - `id`, `name`, `short_name`, `city`, `country`, `created_at`.
- Migration: `src/infrastructure/team/migrations/003_team_is_own.sql` adds `is_own BOOLEAN NOT NULL DEFAULT FALSE` (additive, idempotent, no backfill).
