# Tasks: clip-item-description

Add an optional 200-character description to clip collection items across domain, infrastructure, application, HTTP, and tests.

## Implementation Order

1. Domain entity change
2. Database migration
3. Repository read/write + update method
4. Application ports and use cases
5. HTTP router, payloads, and PATCH endpoint
6. Bootstrap wiring
7. Unit and integration tests

## Tasks

### Domain

- [x] Add `description: str | None` to `ClipCollectionItem` in `src/domain/clip_collections/entities.py`.

### Infrastructure

- [x] Create `src/infrastructure/clip_collections/migrations/002_clip_item_description.sql` adding `description TEXT NULL` with `IF NOT EXISTS`.
- [x] Read and persist `description` in `add_items`, `list_items`, and `get_item` in `src/infrastructure/clip_collections/postgres_repository.py`.
- [x] Add `update_item_description` method to `PostgresClipCollectionRepository` in `src/infrastructure/clip_collections/postgres_repository.py`.

### Application

- [x] Add `description: str | None` to `PendingClipItem` and the repository port in `src/application/clip_collections/ports.py`.
- [x] Thread `description` through add-clip commands in `src/application/clip_collections/use_cases.py`.
- [x] Implement `UpdateClipDescriptionCommand` and use case in `src/application/clip_collections/use_cases.py`.

### Interfaces / HTTP

- [x] Add optional `description` field with `Field(max_length=200)` to `ClipPayload` in `src/interfaces/http/routes/clip_collections_router.py`.
- [x] Add `UpdateClipPayload` model and PATCH `/clips/{item_id}` endpoint in `src/interfaces/http/routes/clip_collections_router.py`.
- [x] Include `description` in `_item_to_dict` in `src/interfaces/http/routes/clip_collections_router.py`.
- [x] Register `update_clip_description_use_case` in `src/interfaces/http/bootstrap/dependencies.py`.
- [x] Pass the new use case into the router factory in `src/interfaces/http/bootstrap/router_wiring.py`.

### Tests

- [x] Update `tests/application/clip_collections/test_clip_collection_use_cases.py` with create, batch, and update description scenarios.
- [x] Update `tests/interfaces/http/test_clip_collections_router.py` with max-length, missing, and PATCH tests.
- [x] Update `tests/integration/test_clip_collections_integration.py` with end-to-end description persistence and migration idempotency.

## Review Workload Forecast

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: size-exception
400-line budget risk: High

Delivery strategy: single-pr
