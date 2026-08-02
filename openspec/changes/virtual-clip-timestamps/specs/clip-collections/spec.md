# Delta for clip-collections

## ADDED Requirements

### Requirement: Clip Range Validation

On creation the system MUST validate: `start_ms >= 0`, `end_ms > start_ms`, `end_ms - start_ms <= 30000`, `end_ms <= video.duration_ms`. Violations MUST return 400 `INVALID_CLIP_RANGE`, persisting nothing; batches are atomic. If `video.duration_ms` is NULL, only the upper-bound check is skipped.

#### Scenario: Valid range accepted

- GIVEN an owned video with `duration_ms = 60000`
- WHEN a clip is created with `start_ms = 5000`, `end_ms = 35000`
- THEN the item is persisted with those timestamps
- AND no object is created in the storage bucket

#### Scenario: Violations return 400, batches atomically

- GIVEN an owned video with `duration_ms = 60000`
- WHEN any clip has `start_ms < 0`, `end_ms <= start_ms`, duration `> 30000`, or `end_ms > 60000`
- THEN the response is 400 `INVALID_CLIP_RANGE` and nothing is persisted

#### Scenario: Unknown video duration

- GIVEN a video with `duration_ms` NULL
- WHEN a clip passes the start/order/30s checks
- THEN it is accepted (upper bound not verifiable)

### Requirement: Clip Item Export

The system MUST expose `POST /videos/{video_id}/collections/{collection_id}/clips/{item_id}/export`, synchronously re-encoding the exact `[start_ms, end_ms]` range from the original video (frame-accurate, not keyframe-snapped) and returning 200 `{download_url}`. Exports MUST be cached under `exports/{item_id}.mp4` with a 7-day lifecycle TTL: unexpired cache MUST be served without regeneration; expired cache MUST be transparently regenerated.

#### Scenario: Cache miss generates export

- GIVEN an item with no cached export
- WHEN export is requested
- THEN the exact range is re-encoded, stored at `exports/{item_id}.mp4`, and `{download_url}` is returned

#### Scenario: Cache hit serves cached export

- GIVEN an unexpired cached export
- WHEN export is requested again
- THEN the cached object is served with no re-encode

#### Scenario: Expired export regenerates

- GIVEN the cached export expired under the lifecycle policy
- WHEN export is requested
- THEN a fresh export is generated and returned

#### Scenario: Not found and forbidden

- GIVEN a non-owner or unknown video/collection/item id
- WHEN export is requested
- THEN 403 `FORBIDDEN_TEAM_ACCESS`, or 404 `VIDEO_NOT_FOUND` / `CLIP_COLLECTION_NOT_FOUND` / `CLIP_COLLECTION_ITEM_NOT_FOUND`

## MODIFIED Requirements

### Requirement: Add Clips to Collection

The system MUST add one clip (`POST .../clips`) or many in order (`POST .../clips/batch`) from `{start_ms, end_ms}` integer payloads with sequential positions. Ranges MUST satisfy Clip Range Validation; unknown collections MUST return 404 `CLIP_COLLECTION_NOT_FOUND`.

(Previously: accepted `{filename, cloudflare_url}`, generating a `storage_key` per clip)

#### Scenario: Add single clip with timestamps

- GIVEN an owned collection
- WHEN a clip is added with a valid `{start_ms, end_ms}`
- THEN 201 returns the item exposing `id`, `collection_id`, `start_ms`, `end_ms`, `position`, `created_at`
- AND no `filename`/`storage_key`/`cloudflare_url` fields

#### Scenario: Add batch preserves order

- GIVEN an owned collection
- WHEN a batch of valid ranges is added
- THEN positions are sequential in payload order

### Requirement: Get Collection Detail

The system MUST return collection metadata plus items ordered by position, each exposing `start_ms`/`end_ms` and no storage fields. Unknown collections MUST return 404 `CLIP_COLLECTION_NOT_FOUND`.

(Previously: items exposed `filename`/`storage_key`/`cloudflare_url`)

#### Scenario: Items expose timestamps

- GIVEN an owned collection with items
- WHEN detail is requested
- THEN each item exposes `start_ms`/`end_ms`, `position`, `created_at` and no storage fields

### Requirement: Delete Collection Item

The system MUST delete one item by id (`DELETE .../clips/{item_id}`), returning 204 and removing only the database row — no source storage object exists to clean. Unknown items MUST return 404 `CLIP_COLLECTION_ITEM_NOT_FOUND`. A cached export MAY remain until lifecycle TTL removal.

(Previously: deleted the DB row but orphaned per-clip storage objects)

#### Scenario: Row-only delete

- GIVEN an existing item
- WHEN it is deleted
- THEN 204 is returned, only the row is removed, and no storage deletion occurs

## REMOVED Requirements

### Requirement: Clip Item File Metadata

(Reason: clips are virtual ranges — per-clip files duplicated storage and the client-supplied `cloudflare_url` was trusted unvalidated)
(Migration: destructive migration drops `filename`/`storage_key`/`cloudflare_url`; no production data exists)
