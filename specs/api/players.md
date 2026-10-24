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
  "primary_position": "RW",
  "jersey_number": "10"
}
```

Field constraints:
- `first_name`: string, 1..120 chars
- `last_name`: string, 1..120 chars
- `birth_date`: optional date (`YYYY-MM-DD`) or `null`
- `height_cm`: optional integer, `> 0`, `<= 300`, or `null`
- `weight_kg`: optional integer, `> 0`, `<= 400`, or `null`
- `primary_position`: optional string, 1..120 chars, or `null`; when given it must be a known code
  (`INVALID_POSITION`, 422 otherwise)
- `jersey_number`: optional string of one or two digits (`^[0-9]{1,2}$`), or `null`

`birth_date`, `height_cm`, `weight_kg` and `primary_position` may be omitted or `null`: a player can be created
with just a name (and a jersey number) and completed later. `PUT` is a full replace, so omitting one of them there
clears it to `null`. Responses return `null` for the ones not set.

`jersey_number` is text rather than an integer so that `"00"` stays distinct from
`"0"`, and so the value matches the string form the CV pipeline reads from
jerseys. Numeric JSON input is coerced to text (`7` becomes `"7"`) and a blank or
whitespace-only string is stored as `null`. Omitting the field on update clears
any existing number.

Player response includes:
- `team_id`: nullable UUID, assigned team or `null`.
- `jersey_number`: nullable string, the player's number or `null`.
- `stats`: object, the player's kept statistics (same shape as `GET /players/{player_id}/stats`:
  `games_played`, `points`, `field_goals`, `two_point`, `three_point`, `rebounds`, `assists`, `steals`,
  `blocks`, `turnovers`, `free_throws`; shooting `percentage` is an integer 0..100). The measured fields come
  from the video analyses and are kept up to date in the background; the response never waits for that, so
  a player who has no analysed video yet shows zeros (`games_played: 0`).

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
    "jersey_number": "10",
    "team_id": null,
    "stats": { "games_played": 0, "points": { "total": 0, "per_game": 0 }, "...": "..." }
  }
}
```

- `422 Unprocessable Entity`: invalid payload format/constraints.

### POST /players/bulk
- Creates name-and-jersey-only players straight into one of the scout's teams (used to build a roster from an
  imported box score). All or nothing: one transaction, with the team row locked.
- Body: `{ "team_id": "<uuid>", "players": [{ "first_name": "...", "last_name": "...", "jersey_number": "7" }] }`
  with 1..30 players, `jersey_number` required (`^[0-9]{1,2}$`) and unique inside the request (422 otherwise).
- A jersey number the team already has is skipped, so repeating the request creates nothing twice.
- The team's player stats are caught up once afterwards, in the background.
- `201 Created` response:

```json
{
  "created": [ { "id": "...", "first_name": "Ana", "last_name": "Paz", "birth_date": null, "height_cm": null,
                 "weight_kg": null, "primary_position": null, "jersey_number": "10", "team_id": "...", "stats": {} } ],
  "skipped": [ { "jersey_number": "7", "reason": "jersey_taken" } ]
}
```

- `404 Not Found`: `TEAM_NOT_FOUND` (missing or not the scout's team).
- `422 Unprocessable Entity`: invalid payload.

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
      "jersey_number": "10",
      "team_id": "4c11b90f-a348-42c8-a6f0-2db1416cb6d5",
      "stats": { "games_played": 3, "points": { "total": 24, "per_game": 8 }, "...": "..." }
    }
  ]
}
```

- Each player includes `stats` as last kept from the video analyses (no extra query, no object storage reads).
  If some finished analysis has not been counted yet, the server catches up after the response is sent
  (checked at most once per user per minute); the request never waits for it and never fails because of it.

### PUT /players/{player_id}/team/{team_id}
- Associates a player to an existing team.
- Path params: `player_id` (UUID), `team_id` (UUID).
- Leaves `jersey_number` untouched.
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
    "jersey_number": "10",
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
    "jersey_number": "10",
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
- Optional (nullable since `src/infrastructure/players/migrations/004_player_profile_optional.sql`, which only
  drops the `NOT NULL`s; the `> 0` checks still apply to filled values):
  - `birth_date` (`DATE`)
  - `height_cm` (`INTEGER`, check `> 0`)
  - `weight_kg` (`INTEGER`, check `> 0`)
  - `primary_position` (`VARCHAR(120)`)
- `team_id` (`UUID`, nullable, FK to `teams.id` with `ON DELETE SET NULL`)
- `jersey_number` (`VARCHAR(2)`, nullable, check `^[0-9]{1,2}$`)

Association migration:
- `src/infrastructure/team/migrations/002_player_team_association.sql`

Jersey number migration:
- `src/infrastructure/players/migrations/001_player_jersey_number.sql`
