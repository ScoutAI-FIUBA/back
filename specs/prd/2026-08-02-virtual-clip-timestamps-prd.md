# PRD: Virtual Clips with Timestamps

## 1) Overview

- **Title**: Virtual Clips with Timestamps (clip collections storage rework)
- **Owner**: Backend team
- **Date**: 2026-08-02
- **Status**: Approved

## 2) Problem statement

Clip collections currently store each clip as an independent video file (`filename` + `storage_key` + `cloudflare_url`). Every clip duplicates video bytes, so storage grows linearly with user clips. Deleting a clip, collection, or video only removes the database row and leaves orphaned objects in Cloudflare. The backend also trusts a client-supplied `cloudflare_url` without validation. Since the feature has not shipped to production, this is the cheapest moment to correct the storage model.

## 3) Goals and non-goals

### Goals

- Store clips as virtual time ranges (`start_ms`/`end_ms`) over the original video; zero marginal storage per clip
- Keep the exact same collections functionality: create, list, get detail, add single/batch, delete
- Offer on-demand download of a clip as an MP4 via ephemeral export (7-day cache)
- Eliminate orphaned storage objects and client-supplied URL trust

### Non-goals

- Changing the collections model, ownership/authorization rules, or the video upload pipeline
- Clip thumbnails (optional phase 2)
- Shareable public clip URLs

## 4) Users and use cases

- **Primary users**: video owners (coaches/analysts) building clip collections from their uploaded videos
- **Main use cases**:
  - Mark an in/out range on the video player and save it as a clip in a collection
  - Play back a clip as a time range of the original video
  - Download a clip as a standalone MP4

## 5) Scope

### In scope

- Rewrite `clip_collection_items`: drop `filename`, `storage_key`, `cloudflare_url`; add `start_ms`/`end_ms` with a 30-second max duration constraint (destructive migration authorized, no production data)
- Domain/application updates: timestamp commands, range validation against video duration, new `ExportClipItemUseCase` + `ClipExporterPort`
- New export endpoint with ffmpeg re-encode and deterministic cache key `exports/{item_id}.mp4`
- Bucket lifecycle policy: 7-day TTL on the `exports/` prefix

### Out of scope

- Changes to `videos`, `teams`, auth, or upload flows
- Frontend implementation (considerations listed below)
- Migration of existing clip data (feature not in production; data loss accepted)

## 6) Functional requirements

1. `POST .../clips` and `POST .../clips/batch` accept `{start_ms, end_ms}` instead of `filename`/`cloudflare_url`
2. Clips are validated: `start_ms >= 0`, `end_ms > start_ms`, `end_ms - start_ms <= 30000`, `end_ms <= video.duration_ms`; violations return 400
3. Clip responses expose `start_ms`/`end_ms`; no storage or URL fields
4. `POST .../clips/{item_id}/export` synchronously re-encodes the exact range from the original video (frame-accurate, e.g. `ffmpeg -ss {start} -i {src} -t {dur} -c:v libx264 -preset veryfast`) and returns `{download_url}`
5. Exports are stored under `exports/{item_id}.mp4`; a re-export within the TTL serves the cached object without regenerating
6. Expired exports (>7 days, removed by lifecycle policy) are transparently regenerated on the next export request
7. Deleting a clip, collection, or video removes only database rows; no storage objects are left behind
8. Ownership/authorization behavior remains identical to the current implementation

## 7) Acceptance criteria

- [ ] Creating a clip produces no new object in the bucket
- [ ] Playback of a clip serves exactly the marked range of the original MP4
- [ ] Export returns an MP4 with the exact requested range (frame-accurate, not keyframe-snapped)
- [ ] Re-export within the TTL is a cache hit (no regeneration)
- [ ] Deleting clips/collections/videos leaves zero orphaned storage objects
- [ ] Clips longer than 30 seconds are rejected with 400 on single and batch endpoints
- [ ] Ownership checks behave exactly as before

## 8) API impact

- **New endpoints**: `POST /videos/{video_id}/collections/{collection_id}/clips/{item_id}/export`
- **Endpoint changes**: request/response contracts of `POST .../clips` and `POST .../clips/batch`; item responses replace `filename`/`storage_key`/`cloudflare_url` with `start_ms`/`end_ms`
- **Backward compatibility notes**: breaking change, acceptable — feature exists only on `feat/clip-collections` and has no production data

## 9) Risks and dependencies

- **Risks**: export latency on slow hardware (mitigated: 30s clips re-encode in seconds); lifecycle policy misconfiguration could delete exports early (harmless — regenerated on demand)
- **Dependencies**: ffmpeg available in the runtime image (Dockerfile); bucket lifecycle rule on `exports/` prefix; video `duration_ms` populated for range validation
- **Mitigations**: deterministic export key per item; exports are derivable artifacts, never source of truth (timestamps in Postgres are)

## 10) Rollout and validation

- **Rollout plan**: implement on `feat/clip-collections` replacing the file-per-clip model before the branch merges
- **Metrics to validate success**: storage objects per clip = 0; orphaned objects after deletes = 0; p95 export latency for a 30s clip

## 11) Frontend considerations

1. **Clip creation**: trimmer UI over the player; capture `currentTime` at mark-in/mark-out, clamp to 30s, send `{start_ms, end_ms}`. The current client-side cut-and-upload flow is removed entirely
2. **Playback**: original video is served as progressive MP4, so use Media Fragment URIs — `video.mp4#t={start_s},{end_s}`; no extra player logic needed
3. **Download**: export button → `POST .../export` → short spinner → trigger browser download from `download_url`
4. **UX validation**: enforce end > start, duration ≤ 30s, end ≤ video duration in the UI before calling the API
5. **Thumbnails (optional, phase 2)**: capture frame at `start_ms` via canvas
