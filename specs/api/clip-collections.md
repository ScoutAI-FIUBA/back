# Clip Collections API Contract

## Base
- Prefix: `/videos/{video_id}/collections`
- Resource ids: `video_id`, `collection_id`, `item_id` (UUID)
- All endpoints require authenticated user.
- Access is owner-scoped through the existing video owner plus the video's current team reference.
- Domain errors use envelope:

```json
{ "error": { "code": "...", "message": "...", "details": {} } }
```

## Endpoints

### POST /videos/{video_id}/collections
- Creates a private collection under one owned video.
- Body:

```json
{
  "name": "Highlights",
  "description": "Optional"
}
```

- `201 Created`: `{ "collection": { ... } }`
- Errors:
  - `403 FORBIDDEN_TEAM_ACCESS`
  - `404 VIDEO_NOT_FOUND`

### GET /videos/{video_id}/collections
- Lists collections for one owned video.
- `200 OK`: `{ "collections": [ ... ] }`
- Errors:
  - `403 FORBIDDEN_TEAM_ACCESS`
  - `404 VIDEO_NOT_FOUND`

### GET /videos/{video_id}/collections/{collection_id}
- Returns collection metadata plus ordered items.
- `200 OK`:

```json
{
  "collection": { "id": "...", "video_id": "...", "team_id": "..." },
  "items": [
    {
      "id": "...",
      "start_ms": 5000,
      "end_ms": 15000,
      "position": 1
    }
  ]
}
```

- Errors:
  - `403 FORBIDDEN_TEAM_ACCESS`
  - `404 VIDEO_NOT_FOUND`
  - `404 CLIP_COLLECTION_NOT_FOUND`

### POST /videos/{video_id}/collections/{collection_id}/clips
- Adds one virtual clip time range.
- Body:

```json
{
  "start_ms": 5000,
  "end_ms": 15000
}
```

- `201 Created`: `{ "item": { ... } }`
- Errors:
  - `400 INVALID_CLIP_RANGE` when `start_ms < 0`, `end_ms <= start_ms`, `end_ms - start_ms > 30000`, or `end_ms > video.duration_ms`

### POST /videos/{video_id}/collections/{collection_id}/clips/batch
- Adds multiple virtual clip time ranges in order.
- Body:

```json
{
  "clips": [
    { "start_ms": 5000, "end_ms": 15000 },
    { "start_ms": 18000, "end_ms": 24000 }
  ]
}
```

- `201 Created`: `{ "items": [ ... ] }`
- Errors:
  - `400 INVALID_CLIP_RANGE` with atomic rejection for the whole batch

### POST /videos/{video_id}/collections/{collection_id}/clips/{item_id}/export
- Synchronously re-encodes the exact clip range and returns a download URL.
- `200 OK`:

```json
{
  "download_url": "https://download.example.com/exports/<item_id>.mp4"
}
```

- Export behavior:
  - Cache key is deterministic: `exports/{item_id}.mp4`
  - Cached exports are reused until the storage lifecycle removes them
  - Exports are frame-accurate re-encodes (`ffmpeg`, not stream copy)
- Errors:
  - `403 FORBIDDEN_TEAM_ACCESS`
  - `404 VIDEO_NOT_FOUND`
  - `404 CLIP_COLLECTION_NOT_FOUND`
  - `404 CLIP_COLLECTION_ITEM_NOT_FOUND`
  - `502 CLIP_EXPORT_FAILED`

### DELETE /videos/{video_id}/collections/{collection_id}/clips/{item_id}
- Deletes one collection item.
- `204 No Content`
- Errors:
  - `403 FORBIDDEN_TEAM_ACCESS`
  - `404 VIDEO_NOT_FOUND`
  - `404 CLIP_COLLECTION_NOT_FOUND`
  - `404 CLIP_COLLECTION_ITEM_NOT_FOUND`

## Persistence and migrations

- Migration: `src/infrastructure/clip_collections/migrations/001_clip_collections_foundation.sql`
- Tables:
  - `clip_collections`
  - `clip_collection_items`

## Operational notes

- Clip items persist only `start_ms`, `end_ms`, `position`, and timestamps; no per-clip file metadata is stored.
- When `video.duration_ms` is `NULL`, the API skips only the `end_ms <= duration_ms` validation.
- Runtime must include `ffmpeg` and storage must enforce a 7-day lifecycle rule for the `exports/` prefix.
