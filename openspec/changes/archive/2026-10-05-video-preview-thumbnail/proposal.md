# Proposal: Video Preview Thumbnails

## Intent

Uploaded videos have no preview frame, so the frontend shows no preview before playback. This change extracts one JPEG thumbnail per video and exposes it as a presigned URL via `GET /videos/{id}`.

## Scope

### In Scope
- Nullable `thumbnail_key` on `videos` (new migration).
- `ThumbnailGeneratorPort` + `FFmpegThumbnailGenerator` (2s seek, 640px JPEG, q~3).
- Best-effort generation on completion; lazy fallback on `GET`.
- `DeleteVideoUseCase` deletes the thumbnail too.
- `GET /videos/{id}` adds `presigned_thumbnail_url` (string | null).
- Tests: adapter, use cases, router.

### Out of Scope
- `GET /videos` list; eager backfill.
- Public/stable URLs, CDN, CORS, R2 config.
- Client-side frame capture.

## Capabilities

### New Capabilities
- `video-thumbnails`: lifecycle (generate on READY, lazy fallback), storage key, and presigned retrieval of a JPEG preview.

### Modified Capabilities
None.

## Approach

Mirror `FFmpegClipExporter`: presign source URL → ffmpeg (`-ss 2` before `-i`, `-frames:v 1`, `scale=640:-2`, JPEG) → `R2Storage.upload_file` under `thumbnails/{team_id}/...`. `GetVideoUseCase` presigns at read time; no URL is stored. Generation is best-effort and never fails the upload — null stays null.

## Affected Areas (`src/` relative)

| Area | Impact | Description |
|------|--------|-------------|
| `.../domain/video/entities.py` | Modified | `thumbnail_key` last, default None. |
| `.../video/migrations/003_video_thumbnail_key.sql` | New | Nullable column. |
| `.../video/postgres_video_repository.py` | Modified | Read; `set_thumbnail_key`. |
| `.../application/video/ports.py` | Modified | Generator port; repo method. |
| `.../application/video/use_cases.py` | Modified | Generate, lazy presign, delete. |
| `.../video/ffmpeg_thumbnail_generator.py` | New | Adapter. |
| `.../routes/videos_router.py` | Modified | Add response field. |
| `.../bootstrap/dependencies.py` | Modified | Wire adapter. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Sync ffmpeg blocks request | Med | Best-effort + lazy; bounded timeout. |
| Lazy GET adds latency/failure | Med | Catch and return null. |
| Thumbnail orphaned on delete | Low | Delete both keys. |
| ffmpeg cannot seek 2s | Low | Fall back to frame 0. |

## Rollback Plan

Revert code, redeploy prior image, then `ALTER TABLE videos DROP COLUMN IF EXISTS thumbnail_key;`. R2 objects are harmless and purgeable.

## Dependencies
- `ffmpeg` binary (already required by clip export).

## Success Criteria
- [ ] New upload reaches READY with non-null `thumbnail_key`.
- [ ] `GET /videos/{id}` returns a working `presigned_thumbnail_url`.
- [ ] Legacy video is backfilled on first GET.
- [ ] Thumbnail failure never fails upload; returns null.
- [ ] Delete removes both objects.

## Review Workload Forecast

Production ~140 lines + tests ~250 = ~390–450 changed lines. 400-line budget risk: **Medium** (borderline). Chained PRs recommended: **No** — single vertical slice; accept size exception if the final diff exceeds 400. Decision needed before apply: **No**.
