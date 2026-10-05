# Design: Per-Clip Description on Collection Items

## Technical Approach

Extend the existing clip-collections capability vertically through all hexagonal layers. Add an optional nullable `description` field to clip items, validate its length at the HTTP boundary, persist it in PostgreSQL, and expose it on create, batch, detail, and a new PATCH update endpoint. No domain invariants change beyond the API-level 200-character limit.

## Architecture Decisions

| Decision | Options | Tradeoffs | Choice |
|----------|---------|-----------|--------|
| Length validation layer | HTTP pydantic vs application use case | pydantic gives automatic 422 and keeps use cases free of string-length concerns; use-case validation would require explicit error mapping | pydantic `Field(max_length=200)` on router payloads |
| Nullability | `TEXT NULL` with entity `str \| None` vs empty string default | Nullable preserves explicit absence and matches existing collection description pattern; empty string conflates missing and blank | Nullable `str \| None` throughout |
| Update endpoint scope | PATCH only description vs PATCH all mutable fields | Narrow scope matches proposal intent and avoids partial-time-range complexity; all-fields patch would require richer validation | PATCH only `description` |
| Repository update pattern | Dedicated `update_item_description` vs generic `update_item` | Dedicated method is explicit, owner-scoped, and matches the single mutable field; generic update adds unused flexibility | Dedicated `update_item_description` |
| Migration safety | `IF NOT EXISTS` additive column vs full rewrite | Additive column is instant, reversible, and preserves data; rewrite is unnecessary | `ALTER TABLE ... ADD COLUMN IF NOT EXISTS description TEXT NULL` |

## Data Flow

### Create single clip with description

```
HTTP router ──ClipPayload──▶ AddClipUseCase ──AddClipBatchCommand──▶ AddClipBatchUseCase
                                                                  │
                              OwnedVideoLookupPort (assert owner) │
                              IdGeneratorPort                     │
                              UnitOfWorkPort                      ▼
                                                  PostgresClipCollectionRepository.add_items
                                                  (description persisted in INSERT)
```

### Update clip description

```
HTTP router ──UpdateClipPayload──▶ UpdateClipDescriptionUseCase
                                    │
                                    ▼
                  PostgresClipCollectionRepository.update_item_description
                  (owner-scoped UPDATE on clip_collection_items)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/domain/clip_collections/entities.py` | Modify | Add `description: str \| None` to `ClipCollectionItem`. |
| `src/infrastructure/clip_collections/migrations/002_clip_item_description.sql` | Create | Add `description TEXT NULL` to `clip_collection_items`. |
| `src/infrastructure/clip_collections/postgres_repository.py` | Modify | Include `description` in insert/select/row mapping; add `update_item_description`. |
| `src/application/clip_collections/ports.py` | Modify | Add `description: str \| None` to `PendingClipItem`; add `update_item_description` to port. |
| `src/application/clip_collections/use_cases.py` | Modify | Add `description` to `AddClipCommand`/`AddClipBatchCommand`; add `UpdateClipDescriptionCommand` and `UpdateClipDescriptionUseCase`. |
| `src/application/clip_collections/errors.py` | No change | Existing `CLIP_COLLECTION_ITEM_NOT_FOUND` and `CLIP_COLLECTION_NOT_FOUND` reused. |
| `src/interfaces/http/routes/clip_collections_router.py` | Modify | Add `description` to `ClipPayload`; add `UpdateClipPayload`; include `description` in `_item_to_dict`; add PATCH endpoint; wire new use case. |
| `src/interfaces/http/bootstrap/dependencies.py` | Modify | Add `update_clip_description_use_case` to `HttpDependencies` and construct it. |
| `src/interfaces/http/bootstrap/router_wiring.py` | Modify | Pass `update_clip_description_use_case` into `create_clip_collections_router`. |
| `tests/application/clip_collections/test_clip_collection_use_cases.py` | Modify | Add/update tests for description on add/batch and update use case. |
| `tests/interfaces/http/test_clip_collections_router.py` | Modify | Add tests for description in payloads and PATCH endpoint. |
| `tests/integration/test_clip_collections_integration.py` | Modify | Add happy-path and validation tests for description. |

## Interfaces / Contracts

```python
# domain
@dataclass(frozen=True)
class ClipCollectionItem:
    id: str
    collection_id: str
    start_ms: int
    end_ms: int
    description: str | None
    position: int
    created_at: datetime

# application port
@dataclass(frozen=True)
class PendingClipItem:
    item_id: str
    start_ms: int
    end_ms: int
    description: str | None

# application command
@dataclass(frozen=True)
class UpdateClipDescriptionCommand:
    user_id: str
    video_id: str
    collection_id: str
    item_id: str
    description: str | None

# router payload
class ClipPayload(BaseModel):
    start_ms: int
    end_ms: int
    description: str | None = Field(default=None, max_length=200)

class UpdateClipPayload(BaseModel):
    description: str | None = Field(default=None, max_length=200)
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|--------------|----------|
| Unit — use cases | `description` carried through add/batch, update command maps 404, missing collection/item, null clear | Extend `_CollectionsRepo` to include `description`; add `update_item_description` |
| Unit — router | Payload max-length returns 422, PATCH routes to correct use case, response shape includes `description` | FastAPI `TestClient` with stub use cases |
| Integration | End-to-end create with/without description, batch mixed descriptions, PATCH update/clear/too long/not found | Reuse existing fixtures and `_apply_migrations` |
| Migration | `002` applies idempotently on current and legacy schema | Add assertion in existing migration convergence test |

## Migration / Rollout

1. Deploy migration `002_clip_item_description.sql` first — additive `TEXT NULL` column is safe and instant.
2. Deploy code changes in dependency order: domain → application → infrastructure → interfaces.
3. Rollback: revert code, then run `ALTER TABLE clip_collection_items DROP COLUMN IF EXISTS description;`.

No feature flags are required because the field is optional and backwards-compatible.

## Open Questions

- None — all proposal question-round assumptions are accepted as constraints for this change.
