# Tasks: Virtual Clip Timestamps

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 650-900 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 schema+domain → PR 2 export infra → PR 3 HTTP+docs |
| Delivery strategy | ask-always |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Replace file metadata with timestamp model | PR 1 | Base branch; include unit+repo tests |
| 2 | Add ffmpeg export adapter and runtime support | PR 2 | Depends on PR 1; include infra tests |
| 3 | Expose export endpoint and docs | PR 3 | Depends on PR 2; include HTTP+integration tests |

## Phase 1: Foundation

- [x] 1.1 Rewrite `src/infrastructure/clip_collections/migrations/001_clip_collections_foundation.sql` to `start_ms`/`end_ms`, DB checks, and no file metadata columns.
- [x] 1.2 Update `src/domain/clip_collections/entities.py` and `src/application/clip_collections/ports.py` for timestamp items, `OwnedVideoContext(duration_ms, storage_key)`, and `ClipExporterPort`.
- [x] 1.3 Update `src/infrastructure/video/postgres_video_repository.py` and `src/infrastructure/clip_collections/postgres_repository.py` for video context, timestamp inserts/reads, and item lookup needed by export.
- [x] 1.4 Update `tests/infrastructure/clip_collections/test_postgres_clip_collection_repository.py` for timestamp persistence, ordering, and missing-item lookup behavior.

## Phase 2: Application + Export Infrastructure

- [x] 2.1 Replace filename URL flows in `src/application/clip_collections/use_cases.py` with range validation, atomic batch rejection, and delete semantics that leave cached exports untouched.
- [x] 2.2 Extend `src/application/clip_collections/errors.py` with `INVALID_CLIP_RANGE` and export failure mapping used by HTTP.
- [x] 2.3 Create `src/infrastructure/clip_collections/ffmpeg_clip_exporter.py` and extend `src/infrastructure/storage.py` for export existence, source download URL, MP4 upload, and presigned download URL.
- [x] 2.4 Update `tests/application/clip_collections/test_clip_collection_use_cases.py` for valid range, each 400 case, NULL `duration_ms`, cache hit, cache miss, and not-found/forbidden export scenarios.

## Phase 3: HTTP Wiring and End-to-End Behavior

- [x] 3.1 Update `src/interfaces/http/routes/clip_collections_router.py` payloads/responses to `{start_ms,end_ms}` and add `POST /videos/{video_id}/collections/{collection_id}/clips/{item_id}/export`.
- [x] 3.2 Update `src/interfaces/http/bootstrap/dependencies.py` and `Dockerfile` to wire `ExportClipItemUseCase`, exporter dependencies, and install `ffmpeg` in runtime.
- [x] 3.3 Update `tests/interfaces/http/test_clip_collections_router.py` and `tests/interfaces/http/test_main_wiring.py` for new contract, route registration, and 400/403/404/502 mappings.
- [x] 3.4 Update `tests/integration/test_clip_collections_integration.py` for timestamp-only create/detail/delete flow and export cache hit/miss regeneration via patched storage/exporter seams.

## Phase 4: Documentation and Ops

- [x] 4.1 Update `specs/api/clip-collections.md` with timestamp payloads, export endpoint, error matrix, cache behavior, and no storage metadata fields.
- [x] 4.2 Update `README.md` plus any affected API/runtime docs with ffmpeg requirement, export lifecycle prerequisite, and revised clip-collection endpoint behavior.
