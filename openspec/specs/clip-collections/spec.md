# clip-collections Specification

## Purpose

Owner-scoped collections of clip items attached to a single owned video. Baseline: each item is an independent video file referenced by `filename`, server-generated `storage_key`, and client-supplied `cloudflare_url`. All endpoints require authentication and are owner-scoped: video must exist and belong to the caller, else 404 `VIDEO_NOT_FOUND` / 403 `FORBIDDEN_TEAM_ACCESS`.

## Requirements

### Requirement: Create Collection

The system MUST let the video owner create a named collection under one owned video via `POST /videos/{video_id}/collections`.

#### Scenario: Happy path

- GIVEN an owned video
- WHEN a collection is created with a valid name
- THEN 201 returns the created collection

#### Scenario: Not found or forbidden

- GIVEN an unknown video or a non-owner caller
- WHEN creating a collection
- THEN the response is 404 `VIDEO_NOT_FOUND` or 403 `FORBIDDEN_TEAM_ACCESS`

### Requirement: List Collections

The system MUST list the caller's collections for one owned video, newest first.

#### Scenario: Happy path

- GIVEN an owned video with collections
- WHEN collections are listed
- THEN 200 returns them ordered by created_at DESC

### Requirement: Get Collection Detail

The system MUST return collection metadata plus its items ordered by position.

#### Scenario: Happy path

- GIVEN an owned collection with items
- WHEN detail is requested
- THEN 200 returns the collection and items exposing `filename`, `storage_key`, `cloudflare_url`, `position`, `created_at`

#### Scenario: Collection not found

- GIVEN an unknown collection id under an owned video
- WHEN detail is requested
- THEN 404 `CLIP_COLLECTION_NOT_FOUND`

### Requirement: Add Clips to Collection

The system MUST add one clip (`POST .../clips`) or many in order (`POST .../clips/batch`) from `{filename, cloudflare_url}` payloads, assigning sequential positions. Unknown collections MUST return 404.

#### Scenario: Add single clip

- GIVEN an owned collection
- WHEN a clip is added with filename and cloudflare_url
- THEN 201 returns the item with a server-generated `storage_key` and next position

#### Scenario: Add batch preserves order

- GIVEN an owned collection
- WHEN a batch of clips is added
- THEN items receive sequential positions in payload order

### Requirement: Clip Item File Metadata

The system MUST persist per-clip `filename`, a unique server-generated `storage_key` (`user/{u}/team/{t}/video/{v}/collection/{c}/clips/{id}-{filename}`), and the client-supplied `cloudflare_url` without validation.

#### Scenario: Storage key generated server-side

- GIVEN a clip add request
- WHEN the item is persisted
- THEN `storage_key` follows the canonical pattern and `cloudflare_url` is stored as provided

### Requirement: Delete Collection Item

The system MUST delete one item by id (`DELETE .../clips/{item_id}`), returning 204. Unknown items MUST return 404 `CLIP_COLLECTION_ITEM_NOT_FOUND`. Only the database row is removed; storage objects are not touched.

#### Scenario: Happy path

- GIVEN an existing item
- WHEN it is deleted
- THEN 204 and the row is gone

#### Scenario: Item not found

- GIVEN an unknown item id
- WHEN delete is requested
- THEN 404 `CLIP_COLLECTION_ITEM_NOT_FOUND`
