# Proposal: Per-Clip Description on Collection Items

## Intent

Allow users to attach a short, optional text description to each clip in a collection so clips can be labeled, annotated, or searched later without changing the export flow.

## Scope

### In Scope
- Add nullable `description` to `ClipCollectionItem` domain model and DB.
- Migration `002_clip_item_description.sql` adding `TEXT NULL` column.
- Repository, application DTOs, and use-case commands updated to carry `description`.
- HTTP API `ClipPayload` accepts optional `description` with 200-char limit.
- GET collection detail returns `description` on each item.
- PATCH endpoint to edit a clip's description after creation.
- Tests for create, batch, missing description, max-length rejection, and edit.

### Out of Scope
- Full-text search or filtering by description.
- Export file naming or storage changes.
- Editing start/end time or other clip fields after creation (only description is editable).

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `clip-collections`: Add and retrieve an optional per-clip `description` on single-clip and batch clip creation, and include it in collection detail responses.

## Approach

Extend the existing clip-collections capability vertically: entity → migration → repository → application DTOs/use cases → router payload/response. Description is nullable with API-level length validation; no new domain invariants. A PATCH endpoint allows editing the description after creation to fix typos.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/domain/clip_collections/entities.py` | Modified | Add `description: str \| None`. |
| `src/infrastructure/clip_collections/migrations/002_clip_item_description.sql` | New | Add `description TEXT NULL`. |
| `src/infrastructure/clip_collections/postgres_repository.py` | Modified | Read/write `description`. |
| `src/application/clip_collections/ports.py` | Modified | Add `description` to `PendingClipItem`. |
| `src/application/clip_collections/use_cases.py` | Modified | Add `description` to add commands. |
| `src/interfaces/http/routes/clip_collections_router.py` | Modified | `ClipPayload.description`, `_item_to_dict`, and new PATCH endpoint. |
| `tests/...` | Modified | Router, integration, and use-case tests. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Migration fails on large tables | Low | `IF NOT EXISTS` additive column; no data rewrite. |
| API clients ignore new optional field | Low | Nullable default preserves backwards compatibility. |
| 200-char limit too restrictive | Low | Confirmed via proposal question round. |

## Rollback Plan

1. Revert code changes in reverse dependency order.  
2. Roll back migration with `ALTER TABLE clip_collection_items DROP COLUMN IF EXISTS description;`.  
3. Re-deploy previous release.

## Dependencies

None.

## Success Criteria

- [ ] Create single clip with description returns 201 and persists value.
- [ ] Create single clip without description returns 201 with `null` description.
- [ ] Batch create with mixed descriptions preserves order and values.
- [ ] Description longer than 200 chars returns 422.
- [ ] GET collection detail includes `description` for each item.
- [ ] PATCH clip description updates the value and rejects descriptions longer than 200 chars.
- [ ] PATCH clip description returns 404 for missing clip or collection.

## Proposal question round

The following assumptions are baked into this proposal; please confirm or correct:

1. **Length limit**: A 200-character max is sufficient for all intended use cases (annotations, labels, short notes). Is this correct, or do you need more?
2. **Mutability**: Description can be edited after creation via a PATCH endpoint to fix typos. Only the description is editable; start/end times remain immutable. Is that acceptable?
3. **Scope of exposure**: Description should be returned to any caller who can view the collection, with no extra privacy gating. OK?
4. **Export behavior**: Description is metadata-only and will not appear in filenames or exported manifests. Confirm.
5. **Search**: No search/filter by description in this slice. Deferred to a later change. Confirm.

Current baked-in assumptions: description is optional/nullable; 200-char API limit; Postgres `TEXT NULL`; no full-text search; description editable via PATCH after creation; no export impact.
