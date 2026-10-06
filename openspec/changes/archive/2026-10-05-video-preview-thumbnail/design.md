# Design: Video Preview Thumbnails

## Technical Approach

Mirror `FFmpegClipExporter`: presign the source, run ffmpeg once in a `TemporaryDirectory`, upload the JPEG via `R2Storage.upload_file`, persist a deterministic key on `videos.thumbnail_key`. Generation is best-effort on completion and lazily on `GET /videos/{id}`; failure leaves the column null and never fails the request. Presigned URLs are produced at read time.

## Architecture Decisions

| # | Decision | Choice | Alternatives | Rationale |
|---|----------|--------|--------------|-----------|
| 1 | Generator dependency | Depend on concrete `R2Storage` | Narrow storage port | Matches `FFmpegClipExporter`; needs `upload_file`/`generate_presigned_url`, absent from `VideoStoragePort`. |
| 4 | Storage key | `thumbnails/{team_id}/{video_id}.jpg` | Derive from `storage_key` | `storage_key` embeds a random UUID; `video.id` + `team_id` are stable and present. |
| 5 | Persistence | Nullable column + `set_thumbnail_key` | Reuse `updated_at` only | One migration, one repo method, no read-model coupling. |
| 7 | HTTP exposure | Presign at read time into `presigned_thumbnail_url` | Persist a URL | URLs expire; mirrors `presigned_playback_url`. `_video_to_dict` is untouched so `GET /videos` gains no field. |
| 8 | Wiring | Inject into Complete + Get; Delete reuses `storage` | Inject into all three | Only Complete/Get generate; Delete already holds `VideoStoragePort`. |
| 10 | Config | Constructor defaults (`ffmpeg_binary="ffmpeg"`, `seek_seconds=2`, `width=640`, `qscale=3`, `timeout_seconds=15`) | Env vars | Matches `FFmpegClipExporter`; scope is code-only. |

### ADR 2 — Synchronous bounded generation on complete

**Choice**: After `complete_upload` commits, call the generator synchronously bounded by `subprocess.run(timeout=15)`, wrapped in `except Exception: pass`. On success persist via `set_thumbnail_key` inside `uow.transaction()`; on failure return the READY video with `thumbnail_key=None`.

**Alternatives**: background worker (none exists); fire-and-forget thread (no error handling).

**Rationale**: Only this path knows the video just became READY. One frame is ~1–2s; a 15s cap bounds worst-case latency. On `TimeoutExpired`, `subprocess.run` kills the child, the temp dir is cleaned, the exception is swallowed, and the upload still returns 200 with null. A failed `set_thumbnail_key` leaves a harmless orphan a later lazy GET overwrites.

### ADR 3 — Lazy fallback and the concurrent-GET race

**Choice**: In `GetVideoUseCase`, when READY and `thumbnail_key is None`, generate once with the same bounded timeout, persist on success, then presign; failures yield `presigned_thumbnail_url: null`.

**Alternatives**: per-video `threading.Lock`; DB advisory lock / conditional `UPDATE`.

**Rationale**: Accept duplicate CPU work. Two concurrent GETs may both generate, but the deterministic key makes the write idempotent (last write wins) and a single S3/R2 PUT is atomic, so no reader sees a partial JPEG. Duplicates are rare and time-bounded. An in-process lock does not help multi-worker deployments; a DB lock is heavier still.

## Data Flow

    Upload complete ─→ generate ─→ set_thumbnail_key → DB
    GET /videos/{id} → (null? generate once) → presign playback + thumbnail

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/infrastructure/video/migrations/003_video_thumbnail_key.sql` | Create | `ADD COLUMN IF NOT EXISTS thumbnail_key TEXT NULL`. |
| `src/domain/video/entities.py` | Modify | Append `thumbnail_key: str \| None = None` last. |
| `src/application/video/ports.py` | Modify | Add `ThumbnailGeneratorPort.generate`; repo `set_thumbnail_key`. |
| `src/infrastructure/video/ffmpeg_thumbnail_generator.py` | Create | Mirrors the clip exporter; retries `-ss 0` when the 2s seek yields no frame. |
| `src/infrastructure/video/postgres_video_repository.py` | Modify | `_row_to_video` reads the column; add `set_thumbnail_key`. |
| `src/application/video/use_cases.py` | Modify | Generate on complete; lazy + 3-tuple return on get; best-effort delete. |
| `src/interfaces/http/routes/videos_router.py` | Modify | Add `presigned_thumbnail_url` to the get response only. |
| `src/interfaces/http/bootstrap/dependencies.py` | Modify | Construct `FFmpegThumbnailGenerator`; inject into Complete + Get. |

## Interfaces / Contracts

- `ThumbnailGeneratorPort.generate(*, source_key: str, thumbnail_key: str) -> None`.
- `VideoRepositoryPort.set_thumbnail_key(*, video_id, team_id, thumbnail_key) -> Video | None`.
- `GetVideoUseCase.execute` returns `tuple[Video, str, str | None]` → `(video, presigned_playback_url, presigned_thumbnail_url)`.
- Delete: after the source delete, if `thumbnail_key` is set, call `storage.delete_video(thumbnail_key)` inside `contextlib.suppress(Exception)`; null keys are skipped and thumbnail failure never blocks source deletion.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|--------------|----------|
| Unit (use cases) | complete success/timeout, lazy backfill/failure→null, delete both / null skip | Fake generator + fake storage |
| Adapter | args (`-ss 2`, `-frames:v 1`, `scale=640:-2`, `.jpg`), `upload_file` key + `image/jpeg`, seek fallback to frame 0 | `MagicMock` storage + patched `subprocess.run` |
| Router | get returns a value and null; complete still 200 on failure | Stub GetUC returning a 3-tuple |

`test_command: "pytest"`. Unit tests need no DB.

## Migration / Rollout

Additive nullable column; deploy before code reads it. Legacy rows backfill on first GET. No R2 bucket/CORS/console change. Rollback: revert code, redeploy, then `ALTER TABLE videos DROP COLUMN IF EXISTS thumbnail_key;`.

## Review Workload Forecast

Production ~140 lines + tests ~250 = ~390–450 changed lines.
Decision needed before apply: No
Chained PRs recommended: No
400-line budget risk: Medium — single vertical slice; accept a size exception if the final diff exceeds 400.

## Open Questions

None.
