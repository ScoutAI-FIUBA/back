# clip-collections Specification

## Purpose

Owner-scoped collections of clip items attached to a single owned video. Each item represents a virtual time range (`start_ms`, `end_ms`) within the parent video, plus an optional text `description` and a sequential `position` inside the collection. The actual video segment is materialized on demand via the export endpoint. All endpoints require authentication and are owner-scoped: the video must exist and belong to the caller, else 404 `VIDEO_NOT_FOUND` / 403 `FORBIDDEN_TEAM_ACCESS`.

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
- THEN 200 returns the collection and items exposing `start_ms`, `end_ms`, `description`, `position`, `created_at`

#### Scenario: Collection not found

- GIVEN an unknown collection id under an owned video
- WHEN detail is requested
- THEN 404 `CLIP_COLLECTION_NOT_FOUND`

### Requirement: Add Clips to Collection

The system MUST add one clip (`POST .../clips`) or many in order (`POST .../clips/batch`) from `{start_ms, end_ms, description?}` payloads, assigning sequential positions. Unknown collections MUST return 404. Clip duration MUST NOT exceed 30 seconds and `end_ms` MUST be greater than `start_ms`.

#### Scenario: Add single clip

- GIVEN an owned collection
- WHEN a clip is added with start_ms, end_ms, and optional description
- THEN 201 returns the item with the next position

#### Scenario: Add batch preserves order

- GIVEN an owned collection
- WHEN a batch of clips is added
- THEN items receive sequential positions in payload order

#### Scenario: Invalid time range

- GIVEN an owned collection
- WHEN a clip is added with end_ms <= start_ms, negative start_ms, duration > 30s, or end_ms beyond video duration
- THEN 422 `INVALID_CLIP_RANGE`

#### Scenario: Description too long

- GIVEN an owned collection
- WHEN a clip is added with a description longer than 200 characters
- THEN 422 validation error

### Requirement: Update Clip Description

The system MUST let the owner update the `description` of an existing clip via `PATCH /videos/{video_id}/collections/{collection_id}/clips/{item_id}`. Only `description` is mutable; `start_ms` and `end_ms` remain immutable after creation.

#### Scenario: Happy path

- GIVEN an owned clip item
- WHEN the description is updated with a valid value
- THEN 200 returns the updated item

#### Scenario: Description too long

- GIVEN an owned clip item
- WHEN the description is longer than 200 characters
- THEN 422 validation error

#### Scenario: Item not found

- GIVEN an unknown item id
- WHEN update is requested
- THEN 404 `CLIP_COLLECTION_ITEM_NOT_FOUND`

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

### Requirement: Export Clip

The system MUST materialize a clip segment on demand via `POST .../clips/{item_id}/export`, returning a time-limited download URL. If the export file already exists, the existing URL MUST be returned without re-processing.

#### Scenario: Happy path

- GIVEN an owned clip item
- WHEN export is requested
- THEN 200 returns a presigned download URL for the segment

#### Scenario: Export fails

- GIVEN an owned clip item and a source video that cannot be processed
- WHEN export is requested
- THEN 500 `CLIP_EXPORT_FAILED`

## Data Model

### `clip_collections`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| video_id | UUID FK -> videos | CASCADE delete |
| team_id | UUID FK -> teams | CASCADE delete |
| owner_user_id | TEXT FK -> users | CASCADE delete |
| name | VARCHAR(180) | NOT NULL |
| description | TEXT | NULL |
| created_at | TIMESTAMPTZ | NOT NULL |
| updated_at | TIMESTAMPTZ | NOT NULL |

### `clip_collection_items`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| collection_id | UUID FK -> clip_collections | CASCADE delete |
| start_ms | INTEGER | NOT NULL, >= 0 |
| end_ms | INTEGER | NOT NULL, > start_ms, <= start_ms + 30000 |
| description | TEXT | NULL, max 200 chars at API |
| position | INTEGER | NOT NULL, > 0, unique per collection |
| created_at | TIMESTAMPTZ | NOT NULL |
