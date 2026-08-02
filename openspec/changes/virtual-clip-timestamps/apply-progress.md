# Apply Progress: virtual-clip-timestamps

## Implementation Progress

**Change**: virtual-clip-timestamps  
**Mode**: Standard

### Completed Tasks
- [x] 1.1 Rewrite migration to timestamp-only clip items with DB constraints.
- [x] 1.2 Update domain/application contracts for virtual clips and exporter port.
- [x] 1.3 Update repositories for timestamp persistence, export lookup, and enriched video context.
- [x] 1.4 Update repository tests for timestamp items and export lookup.
- [x] 2.1 Replace filename flows with range validation, atomic batch rejection, and row-only delete semantics.
- [x] 2.2 Add `INVALID_CLIP_RANGE` and `CLIP_EXPORT_FAILED` HTTP mappings.
- [x] 2.3 Add ffmpeg exporter adapter and storage helpers for cache/export URLs.
- [x] 2.4 Extend application tests for range validation, NULL duration, cache hit/miss, and export failures.
- [x] 3.1 Update HTTP clip payloads/responses and add synchronous export endpoint.
- [x] 3.2 Wire export dependencies and install `ffmpeg` in runtime.
- [x] 3.3 Update router/wiring tests for timestamp contract and export route/error mappings.
- [x] 3.4 Update integration coverage for timestamp clip flow and export cache behavior.
- [x] 4.1 Update API contract docs for timestamp clips and export behavior.
- [x] 4.2 Update README runtime/API notes for ffmpeg and export lifecycle prerequisites.

### Files Changed
| File | Action | What Was Done |
|------|--------|---------------|
| `src/domain/clip_collections/entities.py` | Modified | Replaced file metadata fields with `start_ms` / `end_ms`. |
| `src/application/clip_collections/ports.py` | Modified | Extended owned video context, pending clip item shape, and added exporter port. |
| `src/application/clip_collections/use_cases.py` | Modified | Added range validation and synchronous export use case. |
| `src/application/clip_collections/errors.py` | Modified | Added invalid-range and export-failure codes. |
| `src/infrastructure/clip_collections/postgres_repository.py` | Modified | Persisted/read timestamp clip items and added export item lookup. |
| `src/infrastructure/video/postgres_video_repository.py` | Modified | Returned `duration_ms` and source `storage_key` in video context. |
| `src/infrastructure/clip_collections/ffmpeg_clip_exporter.py` | Created | Added ffmpeg + R2 export adapter with deterministic export keys. |
| `src/infrastructure/storage.py` | Modified | Added object existence, generic upload, and download URL helpers. |
| `src/interfaces/http/routes/clip_collections_router.py` | Modified | Switched clip payloads to timestamps and added export endpoint. |
| `src/interfaces/http/bootstrap/dependencies.py` | Modified | Wired exporter and export use case. |
| `src/interfaces/http/bootstrap/router_wiring.py` | Modified | Registered export route dependency. |
| `src/infrastructure/clip_collections/migrations/001_clip_collections_foundation.sql` | Modified | Rewrote schema for timestamp clip items and DB checks. |
| `Dockerfile` | Modified | Installed `ffmpeg` in runtime image. |
| `tests/**clip_collections*`, `tests/infrastructure/test_storage.py`, `tests/interfaces/http/test_main_wiring.py` | Modified | Updated and added coverage for timestamp model, export flow, and wiring. |
| `specs/api/clip-collections.md`, `README.md` | Modified | Updated public contract and runtime prerequisites. |

### Deviations from Design
None — implementation matches design.

### Issues Found
- Integration tests require `DATABASE_URL`; in this environment they were skipped, so end-to-end DB verification still depends on a configured Postgres test database.

### Remediation Updates
- 2026-08-02: Removed route-layer numeric constraints from `ClipPayload` so invalid timestamp payloads reach the clip collection use cases and return the spec-required `400 INVALID_CLIP_RANGE` envelope instead of FastAPI `422`.
- 2026-08-02: Added targeted HTTP tests covering negative `start_ms` for both single and batch clip add endpoints.
- 2026-08-02: Made `001_clip_collections_foundation.sql` replay-safe for legacy branch databases by detecting the old file-metadata item schema, dropping/recreating clip-collection tables once during convergence, and preserving converged timestamp data on later reruns.
- 2026-08-02: Fixed `FFmpegClipExporter.generate_download_url()` so the injected `download_url_ttl_seconds` is used when callers rely on the exporter default, with targeted unit coverage plus an environment-gated migration convergence integration test.

### Remaining Tasks
- [ ] None.

### Workload / PR Boundary
- Mode: size:exception single PR
- Current work unit: Full change
- Boundary: Virtual clip timestamp model, export adapter/endpoint, tests, and docs
- Estimated review budget impact: Above 400 lines as approved by maintainer exception

### Status
14/14 tasks complete. Ready for verify.
