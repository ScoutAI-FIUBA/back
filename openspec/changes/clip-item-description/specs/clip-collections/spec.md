# Delta for clip-collections

## API Contract

| Endpoint | Method | Payload | Response | Status |
|----------|--------|---------|----------|--------|
| `/videos/{video_id}/collections/{collection_id}/clips` | POST | `{start_ms, end_ms, description?}` (description ≤ 200 chars) | `{item}` with `description` | 201 / 404 / 422 |
| `/videos/{video_id}/collections/{collection_id}/clips/batch` | POST | `{clips: [{start_ms, end_ms, description?}]}` | `{items}` with `description` | 201 / 404 / 422 |
| `/videos/{video_id}/collections/{collection_id}` | GET | — | `{collection, items}` where each item has `description` | 200 / 404 |
| `/videos/{video_id}/collections/{collection_id}/clips/{item_id}` | PATCH | `{description?}` (≤ 200 chars, nullable) | `{item}` with updated `description` | 200 / 404 / 422 |

## Domain Model

| Entity | Change |
|--------|--------|
| `ClipCollectionItem` | Add `description: str \| None`. |

## Repository

| Port / Method | Change |
|---------------|--------|
| `PendingClipItem` | Add `description: str \| None`. |
| `add_items` | Persist `description` per item. |
| `list_items` / `get_item` | Return `description`. |
| `update_item_description` | New method: update an item's `description` within an owner-scoped collection. |

## Migration

`src/infrastructure/clip_collections/migrations/002_clip_item_description.sql` MUST add `description TEXT NULL` to `clip_collection_items` with `IF NOT EXISTS`.

## MODIFIED Requirements

### Requirement: Add Clips to Collection

The system MUST add one clip (`POST .../clips`) or many in order (`POST .../clips/batch`) from `{start_ms, end_ms, description?}` payloads, assigning sequential positions. Unknown collections MUST return 404. Each clip `description`, if provided, MUST NOT exceed 200 characters.
(Previously: clips carried only `start_ms` and `end_ms`; `description` was not supported.)

#### Scenario: Add single clip with description

- GIVEN an owned collection
- WHEN a clip is added with `start_ms`, `end_ms`, and a 200-character description
- THEN 201 returns the item with the description persisted

#### Scenario: Add single clip without description

- GIVEN an owned collection
- WHEN a clip is added with only `start_ms` and `end_ms`
- THEN 201 returns the item with `description` as `null`

#### Scenario: Add batch preserves mixed descriptions

- GIVEN an owned collection
- WHEN a batch with mixed `description` values is added
- THEN items receive sequential positions and each description is preserved

#### Scenario: Description too long on add

- GIVEN an owned collection
- WHEN a clip description exceeds 200 characters
- THEN 422 returns a validation error

#### Scenario: Collection not found on add

- GIVEN an unknown collection id
- WHEN adding a clip
- THEN 404 `CLIP_COLLECTION_NOT_FOUND`

### Requirement: Get Collection Detail

The system MUST return collection metadata plus its items ordered by position. Each item MUST expose `id`, `collection_id`, `start_ms`, `end_ms`, `position`, `description`, and `created_at`.
(Previously: items did not include `description`.)

#### Scenario: Detail includes descriptions

- GIVEN an owned collection with items having mixed descriptions
- WHEN detail is requested
- THEN 200 returns items with each `description` value or `null`

#### Scenario: Collection not found on detail

- GIVEN an unknown collection id
- WHEN detail is requested
- THEN 404 `CLIP_COLLECTION_NOT_FOUND`

## ADDED Requirements

### Requirement: Update Clip Description

The system MUST let the video owner update a clip item's `description` via `PATCH /videos/{video_id}/collections/{collection_id}/clips/{item_id}`. The description MUST be nullable and MUST NOT exceed 200 characters when provided. Unknown collections or items MUST return 404.

#### Scenario: Update description

- GIVEN an owned clip item
- WHEN a PATCH sets a valid description
- THEN 200 returns the updated item

#### Scenario: Clear description

- GIVEN an owned clip item with a description
- WHEN a PATCH sets `description` to `null`
- THEN 200 returns the item with `description` as `null`

#### Scenario: Description too long on update

- GIVEN an owned clip item
- WHEN a PATCH description exceeds 200 characters
- THEN 422 returns a validation error

#### Scenario: Item not found on update

- GIVEN an unknown item id or collection id
- WHEN a PATCH is made
- THEN 404 `CLIP_COLLECTION_NOT_FOUND` or `CLIP_COLLECTION_ITEM_NOT_FOUND`
