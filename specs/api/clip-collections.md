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
      "filename": "goal.mp4",
      "storage_key": "user/<user>/team/<team>/video/<video>/collection/<collection>/clips/<clip>-goal.mp4",
      "cloudflare_url": "https://cdn.example.com/goal.mp4",
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
- Adds one clip metadata record.
- Body:

```json
{
  "filename": "goal.mp4",
  "cloudflare_url": "https://cdn.example.com/goal.mp4"
}
```

- `201 Created`: `{ "item": { ... } }`

### POST /videos/{video_id}/collections/{collection_id}/clips/batch
- Adds multiple clip metadata records in order.
- Body:

```json
{
  "clips": [
    { "filename": "goal.mp4", "cloudflare_url": "https://cdn.example.com/goal.mp4" },
    { "filename": "assist.mov", "cloudflare_url": "https://cdn.example.com/assist.mov" }
  ]
}
```

- `201 Created`: `{ "items": [ ... ] }`

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

- `storage_key` is generated server-side using `user/{user_id}/team/{team_id}/video/{video_id}/collection/{collection_id}/clips/{clip_id}-{filename}`.
- `cloudflare_url` is client-provided metadata persisted alongside the canonical `storage_key`.
