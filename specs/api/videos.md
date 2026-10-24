# Videos API Contract

## Base
- Prefix: `/videos`
- Resource id: `video_id` (UUID)
- All endpoints require authenticated user.
- Domain errors use envelope:

```json
{ "error": { "code": "...", "message": "...", "details": {} } }
```

`details` is optional.

## Endpoints

### POST /videos/upload/init
- Creates video metadata in `PENDING_UPLOAD` and starts a multipart upload session in R2.
- Body:

```json
{
  "team_id": "00000000-0000-4000-8000-000000000001",
  "title": "Training session",
  "description": "Optional",
  "content_type": "video/mp4",
  "part_count": 3
}
```

- `201 Created` response:

```json
{
  "video_id": "00000000-0000-4000-8000-000000000010",
  "storage_key": "videos/<team>/<id>",
  "upload_id": "r2-upload-id",
  "parts": [
    { "part_number": 1, "presigned_part_url": "https://..." },
    { "part_number": 2, "presigned_part_url": "https://..." },
    { "part_number": 3, "presigned_part_url": "https://..." }
  ],
  "expires_at": null,
  "status": "PENDING_UPLOAD"
}
```

- Errors:
  - `403 FORBIDDEN_TEAM_ACCESS`
  - `409 VIDEO_STORAGE_KEY_CONFLICT`

### POST /videos/{video_id}/upload/complete
- Finalizes upload metadata and transitions status to `READY`.
- Body:

```json
{
  "team_id": "00000000-0000-4000-8000-000000000001",
  "mime_type": "video/mp4",
  "size_bytes": 123456,
  "duration_ms": 52000,
  "upload_id": "r2-upload-id",
  "parts": [
    { "part_number": 1, "etag": "\"etag-part-1\"" },
    { "part_number": 2, "etag": "\"etag-part-2\"" }
  ]
}
```

- `200 OK`: `{ "video": { ... } }`
- Errors:
  - `403 FORBIDDEN_TEAM_ACCESS`
  - `409 UPLOAD_NOT_INITIALIZED`

### POST /videos/{video_id}/upload/abort
- Aborts multipart upload session and marks pending upload as failed.
- Body:

```json
{
  "team_id": "00000000-0000-4000-8000-000000000001",
  "upload_id": "r2-upload-id"
}
```

- `204 No Content`
- Errors:
  - `403 FORBIDDEN_TEAM_ACCESS`
  - `409 UPLOAD_NOT_INITIALIZED`

### GET /videos
- Query: `team_id` (required UUID), `status` (optional)
- `200 OK`: `{ "videos": [ ... ] }`
- Errors:
  - `403 FORBIDDEN_TEAM_ACCESS`

### GET /videos/{video_id}
- Query: `team_id` (required UUID)
- `200 OK` response:

```json
{
  "video": { "id": "...", "status": "READY", "storage_key": "..." },
  "presigned_playback_url": "https://..."
}
```

- Errors:
  - `403 FORBIDDEN_TEAM_ACCESS`
  - `404 VIDEO_NOT_FOUND`
  - `409 VIDEO_NOT_READY`

### PATCH /videos/{video_id}
- Body:

```json
{
  "team_id": "00000000-0000-4000-8000-000000000001",
  "title": "Optional title",
  "description": "Optional description",
  "player_ids": ["00000000-0000-4000-8000-000000000111"]
}
```

- `200 OK`: `{ "video": { ... } }`
- Errors:
  - `403 FORBIDDEN_TEAM_ACCESS`
  - `404 VIDEO_NOT_FOUND`
  - `422 PLAYER_TEAM_MISMATCH`

### PUT /videos/{video_id}/match
- Links the video to one of the user's matches, or clears the link. Dedicated endpoint because PATCH treats a missing/`null` field as "unchanged", while here `null` must clear.
- A video belongs to at most one match; a match can have many videos. Linking to another match overwrites the previous link. Deleting is not involved: the link is a nullable `videos.match_id`.
- Body (both fields required; `match_id: null` clears):

```json
{ "team_id": "00000000-0000-4000-8000-000000000001", "match_id": "00000000-0000-4000-8000-0000000000aa" }
```

- `200 OK`: `{ "video": { ..., "match_id": "00000000-0000-4000-8000-0000000000aa" } }`
- Rules: the video must belong to `team_id` and the user and not be deleted; the match must be owned by the user; the video's team must be the match's home or away team.
- Errors:
  - `404 TEAM_NOT_FOUND` (team not owned by the user)
  - `404 VIDEO_NOT_FOUND` (also when `team_id` is not the video's team, or the video is deleted)
  - `404 MATCH_NOT_FOUND` (missing or another user's match)
  - `422 VIDEO_TEAM_NOT_IN_MATCH`
  - `422` (FastAPI validation) for malformed UUIDs or missing fields

### DELETE /videos/{video_id}
- Query: `team_id` (required UUID)
- Success variants:
  - `204 No Content` when DB soft delete + R2 delete succeed.
  - `202 Accepted` with `{ "deleted": true, "compensation_pending": true }` when compensation mode is active.
- Errors:
  - `403 FORBIDDEN_TEAM_ACCESS`
  - `404 VIDEO_NOT_FOUND`
  - `502 STORAGE_DELETE_FAILED`

## Persistence and migrations

- Migration: `src/infrastructure/video/migrations/001_video_management_foundation.sql`
- `src/infrastructure/video/migrations/004_video_match_link.sql` (additive and idempotent): `videos.match_id UUID NULL REFERENCES matches(id) ON DELETE SET NULL` plus a partial index. Existing rows get `NULL`; nothing is dropped, rewritten or backfilled. It must run after the matches migrations (`scripts/apply_migrations.py` already orders them that way).
- Tables:
  - `videos`
  - `video_players`

Every video object returned by the API includes `match_id` (UUID string or `null`). Clients that want the videos of a match filter `GET /videos?team_id=` by `match_id`.

## Operational notes

- Stale `PENDING_UPLOAD` rows are expected when client never calls `upload/complete`; handle with reconciliation/cleanup job.
- Current authorization adapter checks team existence to enforce `TeamAccessPort`; membership-based policy is planned follow-up.
