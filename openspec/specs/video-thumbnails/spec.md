# video-thumbnails Specification

## Purpose

One JPEG preview frame per uploaded video, extracted at the 2-second mark and exposed as a presigned URL via `GET /videos/{id}`. Generation is best-effort and MUST NOT block or fail an upload.

## Storage Key

| Item | Rule |
|------|------|
| Object key | Deterministic `thumbnails/{team_id}/...` |
| Persisted field | `videos.thumbnail_key` (nullable) |
| Format | JPEG, 640px width, aspect ratio preserved |

## Requirements

### Requirement: Generate Thumbnail on Upload Completion

On successful `POST /videos/{video_id}/upload/complete`, when the video becomes READY, the system SHALL generate one JPEG thumbnail from the R2 object at the 2-second mark, scaled to 640px width with aspect ratio preserved, stored under a deterministic `thumbnails/{team_id}/...` key and persisted in `videos.thumbnail_key`. Generation MUST be best-effort: any failure MUST NOT fail or block the upload, and `thumbnail_key` MAY remain null.

#### Scenario: Successful upload generates thumbnail

- GIVEN an upload completes for a video
- WHEN the video becomes READY
- THEN one JPEG is stored under `thumbnails/{team_id}/...`
- AND `videos.thumbnail_key` holds that key

#### Scenario: Generation failure does not fail upload

- GIVEN an upload completes but extraction fails
- WHEN the completion request is processed
- THEN the upload still succeeds
- AND `thumbnail_key` remains null

#### Scenario: Seek unavailable falls back to frame zero

- GIVEN a source whose 2-second seek yields no frame
- WHEN generation runs
- THEN the system SHOULD extract frame 0 instead

### Requirement: Stable Thumbnail Object

Once generated, the thumbnail MUST be one stable object; repeated reads MUST reference it. Presigned URLs MAY rotate per request — accepted.

#### Scenario: Same object across reads

- GIVEN a video with a persisted `thumbnail_key`
- WHEN `GET /videos/{id}` is called twice
- THEN both responses point to the same object

### Requirement: Expose Thumbnail on Get Video

`GET /videos/{id}` MUST return a fresh presigned `presigned_thumbnail_url` when a thumbnail exists, else `null`.

#### Scenario: Video with thumbnail

- GIVEN an owned READY video with a thumbnail
- WHEN `GET /videos/{id}` is requested
- THEN 200 includes a fresh presigned `presigned_thumbnail_url`

#### Scenario: Video without thumbnail

- GIVEN an owned READY video with null `thumbnail_key` and impossible generation
- WHEN `GET /videos/{id}` is requested
- THEN 200 includes `presigned_thumbnail_url` as `null`

### Requirement: Lazy Fallback Generation on Read

When `GET /videos/{id}` finds `thumbnail_key` null, the system SHALL attempt generation once and persist the key on success. On failure the endpoint MUST still succeed with `presigned_thumbnail_url: null`.

#### Scenario: Legacy video is backfilled on first read

- GIVEN an owned READY video with null `thumbnail_key` and a valid source
- WHEN `GET /videos/{id}` is requested
- THEN generation runs once and the key is persisted
- AND a presigned `presigned_thumbnail_url` is returned

#### Scenario: Lazy generation failure still returns 200

- GIVEN an owned READY video with null `thumbnail_key` and an unprocessable source
- WHEN `GET /videos/{id}` is requested
- THEN 200 returns `presigned_thumbnail_url: null`
- AND the request does not error

### Requirement: Delete Thumbnail With Video

Deleting a video MUST also delete its thumbnail object (no orphans).

#### Scenario: Delete removes both objects

- GIVEN an owned video with a source object and a thumbnail
- WHEN the video is deleted
- THEN both the source and thumbnail objects are removed

### Requirement: Access Control

Thumbnail generation and retrieval MUST apply the same team-scoped access control as `GET /videos/{id}`.

#### Scenario: Non-owner is denied

- GIVEN a video owned by another team
- WHEN a caller requests `GET /videos/{id}`
- THEN 403 `FORBIDDEN_TEAM_ACCESS` (or 404 `VIDEO_NOT_FOUND`) is returned

### Requirement: Non-Goals

This capability MUST NOT cover `GET /videos` list output, eager backfill beyond lazy first-read, public/stable URLs, CDN, CORS, R2 bucket configuration, or client-side frame capture.

#### Scenario: List endpoint unchanged

- GIVEN a client requests `GET /videos`
- WHEN the response is built
- THEN no thumbnail field is added by this capability
