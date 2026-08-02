# Proposal: virtual-clip-timestamps

**Source of truth (approved PRD)**: `specs/prd/2026-08-02-virtual-clip-timestamps-prd.md`

## Intent

Rework clip collections so clips are virtual time ranges (`start_ms`/`end_ms`) over the original video instead of duplicated per-clip files, and add on-demand MP4 export with a 7-day cache.

## Capabilities

- **Modified**: `clip-collections`

## Locked product decisions (from PRD — do not reopen)

1. Clips become virtual ranges; `filename`/`storage_key`/`cloudflare_url` are dropped.
2. Max clip duration 30s; validations: `start_ms >= 0`, `end_ms > start_ms`, `end_ms - start_ms <= 30000`, `end_ms <= video.duration_ms` → 400 on violation.
3. New endpoint `POST /videos/{video_id}/collections/{collection_id}/clips/{item_id}/export` → synchronous frame-accurate ffmpeg re-encode, returns `{download_url}`.
4. Exports cached under `exports/{item_id}.mp4` with 7-day lifecycle TTL; expired exports transparently regenerate.
5. Ownership/authorization behavior unchanged.
6. Destructive migration authorized (no production data).

## Rollback

Feature lives only on `feat/clip-collections`; revert the branch. No production data or consumers exist.
