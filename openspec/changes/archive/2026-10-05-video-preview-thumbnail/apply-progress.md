# Apply Progress: Video Preview Thumbnails

**Change**: video-preview-thumbnail
**Mode**: Standard (Strict TDD disabled — `openspec/config.yaml` `apply.tdd: false`)
**Delivery**: single PR with recorded `size:exception` (final diff exceeds the 400-line review budget)
**Branch**: `feat/clip-collections-update` (unchanged; no commit/push performed)

## Completed Tasks

### Phase 1: Foundation
- [x] 1.1 Create `src/infrastructure/video/migrations/003_video_thumbnail_key.sql`.
- [x] 1.2 `src/domain/video/entities.py`: append `thumbnail_key: str | None = None` as the last `Video` field.
- [x] 1.3 `src/application/video/ports.py`: add `ThumbnailGeneratorPort.generate` ABC.
- [x] 1.4 `src/application/video/ports.py`: add `VideoRepositoryPort.set_thumbnail_key`.

### Phase 2: Persistence + Adapter
- [x] 2.1 `postgres_video_repository.py`: `_row_to_video` reads `thumbnail_key=row.get("thumbnail_key")`.
- [x] 2.2 `postgres_video_repository.py`: `set_thumbnail_key` owner-scoped `UPDATE ... RETURNING *`.
- [x] 2.3 Create `ffmpeg_thumbnail_generator.py` mirroring `FFmpegClipExporter`.
- [x] 2.4 Adapter presigns source, runs ffmpeg in a `TemporaryDirectory`, uploads `image/jpeg`.
- [x] 2.5 Adapter retries `-ss 0` when the 2s seek yields no frame; subprocess errors propagate.

### Phase 3: Application Use Cases
- [x] 3.1 `CompleteVideoUploadUseCase`: best-effort generate + `set_thumbnail_key`; errors swallowed.
- [x] 3.2 `GetVideoUseCase`: lazy backfill when READY and `thumbnail_key is None`.
- [x] 3.3 `GetVideoUseCase.execute`: returns `(video, playback_url, presigned_thumbnail_url)`.
- [x] 3.4 `DeleteVideoUseCase`: best-effort thumbnail delete under `contextlib.suppress`.

### Phase 4: HTTP + Wiring
- [x] 4.1 `videos_router.py` `get_video`: unpacks the 3-tuple, adds `presigned_thumbnail_url`; `_video_to_dict` untouched.
- [x] 4.2 `dependencies.py`: constructs `FFmpegThumbnailGenerator(storage=video_storage)`; injects into Complete + Get.

### Phase 5: Tests
- [x] 5.1 `tests/infrastructure/video/test_ffmpeg_thumbnail_generator.py` (args, jpeg upload key/content-type, seek fallback, error propagation).
- [x] 5.2 `tests/application/video/test_use_cases.py` (complete success/failure, lazy backfill/failure, delete both/null-skip/best-effort thumbnail failure).
- [x] 5.3 `tests/interfaces/http/test_videos_router.py` (get value/null, complete 200 when thumbnail missing).
- [x] 5.4 Existing tests updated for the new constructor arg and the 3-tuple return.

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `src/infrastructure/video/migrations/003_video_thumbnail_key.sql` | Created | Additive nullable `thumbnail_key` column. |
| `src/domain/video/entities.py` | Modified | `thumbnail_key: str \| None = None` appended as the last field. |
| `src/application/video/ports.py` | Modified | Added `ThumbnailGeneratorPort`; added `VideoRepositoryPort.set_thumbnail_key`; exported the port. |
| `src/infrastructure/video/postgres_video_repository.py` | Modified | Reads `thumbnail_key`; added owner-scoped `set_thumbnail_key`. |
| `src/infrastructure/video/ffmpeg_thumbnail_generator.py` | Created | ffmpeg JPEG adapter with `-ss 2` → frame 0 fallback. |
| `src/application/video/use_cases.py` | Modified | Complete/lazy generation, 3-tuple get, best-effort thumbnail delete. |
| `src/interfaces/http/routes/videos_router.py` | Modified | `GET /videos/{id}` now returns `presigned_thumbnail_url`. |
| `src/interfaces/http/bootstrap/dependencies.py` | Modified | Wires `FFmpegThumbnailGenerator` into Complete + Get. |
| `tests/infrastructure/video/test_ffmpeg_thumbnail_generator.py` | Created | Adapter unit tests. |
| `tests/infrastructure/video/test_postgres_video_repository.py` | Created | Repository mapper + `set_thumbnail_key` SQL tests (fake connection). |
| `tests/integration/test_video_thumbnail_repository_integration.py` | Created | Real-Postgres round-trip for `set_thumbnail_key` (skips without DB). |
| `tests/application/video/test_use_cases.py` | Modified | Fakes extended; new generation/backfill/delete tests. |
| `tests/interfaces/http/test_videos_router.py` | Modified | `presigned_thumbnail_url` value/null + complete 200 tests. |

## Deviations from Design

- **Return refresh on success.** `CompleteVideoUploadUseCase` and `GetVideoUseCase` return the row from `set_thumbnail_key` when it is non-null, so callers observe the persisted `thumbnail_key`. This is a precision improvement over the literal "return READY video" wording; failure still returns the original READY video with `thumbnail_key=None`. `_video_to_dict` is untouched, so HTTP payloads are unaffected.
- **No source-URL TTL parameter.** Task 2.3 enumerated the adapter defaults and omitted a source TTL; the adapter calls `generate_presigned_url(source_key)` with the `R2Storage` default (3600s) instead of adding an unused knob.

## Issues Found

- **No live PostgreSQL available** in this environment (`127.0.0.1:5435` connection refused). All DB-backed integration tests are written but could not be executed here; they skip on `psycopg.OperationalError`.
- Pre-existing DB-dependent integration tests (`tests/integration/test_postgres_integration.py`, `tests/integration/test_auth_use_cases_integration.py`) fail/error in this environment because no database is reachable. Unrelated to this change and untouched.

## Tests

- Command: `.venv/bin/python -m pytest -m "not integration" -q`
- Result: **378 passed, 31 deselected** (non-DB suite green).
- Targeted video slice: **37 passed**.
- Router file `tests/interfaces/http/test_videos_router.py`: **6 passed** (includes the post-verify W2 regression test).
- DB integration: `tests/integration/test_video_thumbnail_repository_integration.py` + `test_video_management_integration.py` → **4 skipped** ("Postgres not reachable").
- Full integration run (`-m integration`): 1 failed, 22 skipped, 8 errors — all pre-existing DB-unavailable failures, none in files changed by this apply.

## Remaining Tasks

None. All Phase 1–5 tasks are complete.

## Workload / PR Boundary

- Mode: single PR with `size:exception` (maintainer-approved; recorded).
- Current work unit: full vertical slice (coupled 3-tuple return-type change).
- Boundary: migration + domain + ports + adapter + repo + use cases + HTTP + wiring + tests.
- Estimated review budget impact: ~794 added lines vs. the 400-line budget → `size:exception` applies.

## Post-Verify Follow-up (verify W2)

- Added `test_list_videos_does_not_expose_thumbnail_fields` to `tests/interfaces/http/test_videos_router.py`: asserts `GET /videos` items expose neither `thumbnail_key` nor `presigned_thumbnail_url` (regression guard for the non-goal "list endpoint unchanged"). Extended the test helper `_client_with` with an optional `list_uc` and added `_ListOkUC`.
- Result: router file 6 passed; full non-DB suite 378 passed. This resolves verify finding **W2**.

## Status

19/19 tasks complete. Verified (PASS WITH WARNINGS); W2 addressed post-verify. W1 (no live DB) remains an accepted environmental warning.
