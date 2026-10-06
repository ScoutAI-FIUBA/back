# Tasks: Video Preview Thumbnails

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~390–450 (prod ~140 + tests ~250) |
| 400-line budget risk | Medium (borderline) |
| Chained PRs recommended | No |
| Suggested split | Single PR; accept `size:exception` if final diff > 400 |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: Yes
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Medium

One vertical slice: splitting fragments the coupled 3-tuple return-type change. Under single-pr, accept a `size:exception` if the final diff crosses 400.

## Phase 1: Foundation

- [x] 1.1 Create `src/infrastructure/video/migrations/003_video_thumbnail_key.sql`: `ALTER TABLE videos ADD COLUMN IF NOT EXISTS thumbnail_key TEXT NULL`.
- [x] 1.2 `src/domain/video/entities.py`: append `thumbnail_key: str | None = None` as the LAST `Video` field.
- [x] 1.3 `src/application/video/ports.py`: add `ThumbnailGeneratorPort.generate(*, source_key, thumbnail_key) -> None` ABC.
- [x] 1.4 `src/application/video/ports.py`: add `VideoRepositoryPort.set_thumbnail_key(*, video_id, team_id, thumbnail_key) -> Video | None`.

## Phase 2: Persistence + Adapter

- [x] 2.1 `src/infrastructure/video/postgres_video_repository.py`: `_row_to_video` reads `thumbnail_key=row.get("thumbnail_key")`.
- [x] 2.2 Same file: implement `set_thumbnail_key` (owner-scoped `UPDATE ... RETURNING *`).
- [x] 2.3 Create `src/infrastructure/video/ffmpeg_thumbnail_generator.py` mirroring `FFmpegClipExporter`; defaults `ffmpeg_binary="ffmpeg"`, `seek_seconds=2`, `width=640`, `qscale=3`, `timeout_seconds=15`.
- [x] 2.4 Adapter: presign source -> `TemporaryDirectory` -> ffmpeg `-ss 2 -i <url> -frames:v 1 -vf scale=640:-2 -q:v 3 frame.jpg` -> `upload_file(..., "image/jpeg")`.
- [x] 2.5 Adapter: retry `-ss 0` when the 2s seek yields no frame; let subprocess errors propagate (caller swallows).

## Phase 3: Application Use Cases

- [x] 3.1 `CompleteVideoUploadUseCase`: accept `thumbnail_generator`; after commit, best-effort `generate` -> `set_thumbnail_key` inside `uow.transaction()`; swallow all errors, return READY video.
- [x] 3.2 `GetVideoUseCase`: when READY and `thumbnail_key is None`, generate once and persist best-effort.
- [x] 3.3 `GetVideoUseCase.execute`: return `(video, playback_url, presigned_thumbnail_url)`; thumbnail URL from `generate_presigned_url` or `None`.
- [x] 3.4 `DeleteVideoUseCase`: after source delete, `storage.delete_video(thumbnail_key)` when set, under `contextlib.suppress(Exception)`.

## Phase 4: HTTP + Wiring

- [x] 4.1 `src/interfaces/http/routes/videos_router.py` `get_video`: unpack the 3-tuple; add `"presigned_thumbnail_url"`. Leave `_video_to_dict` untouched (`GET /videos` unchanged).
- [x] 4.2 `src/interfaces/http/bootstrap/dependencies.py`: import/construct `FFmpegThumbnailGenerator(storage=video_storage)`; inject into `CompleteVideoUploadUseCase` and `GetVideoUseCase`.

## Phase 5: Tests

- [x] 5.1 Adapter `tests/infrastructure/video/test_ffmpeg_thumbnail_generator.py`: assert ffmpeg args, `upload_file` key + `image/jpeg`, seek fallback (`MagicMock` storage + patched `subprocess.run`).
- [x] 5.2 `tests/application/video/test_use_cases.py`: complete success/timeout, lazy backfill/failure->null, delete both / null-skip (fake generator + storage).
- [x] 5.3 `tests/interfaces/http/test_videos_router.py`: get returns a value and null; complete still 200 on failure.
- [x] 5.4 Update existing tests for the new constructor arg and 3-tuple return; keep tests with their units where possible.
