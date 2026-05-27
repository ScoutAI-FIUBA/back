# ADR Template

- **ADR**: `0001-presigned-first-video-architecture`
- **Date**: 2026-05-27
- **Status**: Accepted

## Context

Video management must support upload and playback with Cloudflare R2 while keeping API latency stable and avoiding large file transfer through the backend. Videos must be associated to multiple players without JSON denormalization.

## Decision

Adopt a multipart-only S3-compatible upload flow for videos:
- Backend starts multipart upload sessions and returns presigned **part** URLs.
- Client uploads all parts directly to R2 and then calls complete with `(part_number, etag)` list.
- Backend supports explicit abort endpoint for failed/cancelled sessions.
- Backend stores metadata in `videos` and many-to-many relations in `video_players`.

Keep business orchestration in application services and storage signing/deletion in infrastructure adapters, following current hexagonal boundaries.

## Consequences

- Positive: API avoids acting as file proxy, reducing bandwidth and scaling pressure.
- Negative: Client complexity increases (part orchestration + ETag bookkeeping).
- Follow-up: Add stale multipart cleanup policy for pending/failed sessions.
