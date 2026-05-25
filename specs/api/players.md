# Players API Contract

## Base
- Prefix: `/players`
- Resource id: `player_id` (UUID)
- Validation errors use FastAPI default 422 format.
- Domain errors use envelope:

```json
{ "error": { "code": "...", "message": "...", "details": {} } }
```

`details` is optional.

## Payload

```json
{
  "first_name": "Lamine",
  "last_name": "Yamal",
  "birth_date": "2007-07-13",
  "height_cm": 180,
  "weight_kg": 72,
  "primary_position": "RW"
}
```

Field constraints:
- `first_name`: string, 1..120 chars
- `last_name`: string, 1..120 chars
- `birth_date`: date (`YYYY-MM-DD`)
- `height_cm`: integer, `> 0`, `<= 300`
- `weight_kg`: integer, `> 0`, `<= 400`
- `primary_position`: string, 1..120 chars

Player response includes:
- `team_id`: nullable UUID, assigned team or `null`.

## Endpoints

### POST /players
- Creates a player.
- Body: Player payload.
- `201 Created` response:

```json
{
  "player": {
    "id": "4a84e16a-bf44-4f9f-9b7c-d309822cdfdb",
    "first_name": "Lamine",
    "last_name": "Yamal",
    "birth_date": "2007-07-13",
    "height_cm": 180,
    "weight_kg": 72,
    "primary_position": "RW",
    "team_id": null
  }
}
```

- `422 Unprocessable Entity`: invalid payload format/constraints.

### GET /players
- Lists players ordered by `last_name ASC, first_name ASC`.
- Optional query param: `team_id` (UUID) to filter players by team.
- `200 OK` response:

```json
{
  "players": [
    {
      "id": "4a84e16a-bf44-4f9f-9b7c-d309822cdfdb",
      "first_name": "Lamine",
      "last_name": "Yamal",
      "birth_date": "2007-07-13",
      "height_cm": 180,
      "weight_kg": 72,
      "primary_position": "RW",
      "team_id": "4c11b90f-a348-42c8-a6f0-2db1416cb6d5"
    }
  ]
}
```

### PUT /players/{player_id}/team/{team_id}
- Associates a player to an existing team.
- Path params: `player_id` (UUID), `team_id` (UUID).
- `200 OK` response:

```json
{
  "player": {
    "id": "4a84e16a-bf44-4f9f-9b7c-d309822cdfdb",
    "first_name": "Lamine",
    "last_name": "Yamal",
    "birth_date": "2007-07-13",
    "height_cm": 180,
    "weight_kg": 72,
    "primary_position": "RW",
    "team_id": "4c11b90f-a348-42c8-a6f0-2db1416cb6d5"
  }
}
```

- `404 Not Found` for missing player (`PLAYER_NOT_FOUND`) or missing team (`TEAM_NOT_FOUND`).
- `422 Unprocessable Entity`: invalid UUIDs.

### PUT /players/{player_id}
- Updates an existing player.
- Path: `player_id` (UUID).
- Body: Player payload.
- `200 OK` response:

```json
{
  "player": {
    "id": "4a84e16a-bf44-4f9f-9b7c-d309822cdfdb",
    "first_name": "Lamine",
    "last_name": "Yamal",
    "birth_date": "2007-07-13",
    "height_cm": 180,
    "weight_kg": 72,
    "primary_position": "RW",
    "team_id": null
  }
}
```

- `404 Not Found`:

```json
{
  "error": {
    "code": "PLAYER_NOT_FOUND",
    "message": "Player not found"
  }
}
```

- `422 Unprocessable Entity`: invalid `player_id` UUID or invalid payload.

### DELETE /players/{player_id}
- Deletes a player.
- Path: `player_id` (UUID).
- `204 No Content` response.
- `404 Not Found`:

```json
{
  "error": {
    "code": "PLAYER_NOT_FOUND",
    "message": "Player not found"
  }
}
```

- `422 Unprocessable Entity`: invalid `player_id` UUID.

## Persistence and migration note

- Migration: `src/infrastructure/auth/migrations/003_players_foundation.sql`
- Table: `players`
- Required fields (`NOT NULL`):
  - `id` (`UUID`, primary key)
  - `first_name` (`VARCHAR(120)`)
  - `last_name` (`VARCHAR(120)`)
  - `birth_date` (`DATE`)
  - `height_cm` (`INTEGER`, check `> 0`)
  - `weight_kg` (`INTEGER`, check `> 0`)
- `primary_position` (`VARCHAR(120)`)
- `team_id` (`UUID`, nullable, FK to `teams.id` with `ON DELETE SET NULL`)

Association migration:
- `src/infrastructure/team/migrations/002_player_team_association.sql`
