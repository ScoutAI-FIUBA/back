# Design: Virtual Clip Timestamps

Clip items become timestamp-only rows over the original video, and export becomes a synchronous ffmpeg re-encode cached at `exports/{item_id}.mp4` for 7 days.

## Technical Approach

Keep the current hexagonal flow: HTTP maps payloads to use cases, use cases enforce ownership and range rules, repositories persist only clip metadata, and infrastructure owns R2 + ffmpeg details. Extend the video ownership lookup to also return `duration_ms` and `storage_key`, so one query supports authz, validation, and export source resolution.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Migration shape | Rewrite `001_clip_collections_foundation.sql` to the final schema | Add `002` ALTER migration | `scripts/apply_migrations.py` replays every `*.sql` on boot and tracks no migration state. Rewriting `001` is the cleanest branch-only reset; destructive change is explicitly allowed. |
| Ownership lookup | Extend `OwnedVideoContext` with `duration_ms: int \| None` and `storage_key: str` | Add separate video-read query for export | One lookup keeps authz unchanged and avoids duplicating video fetch logic in clip use cases. |
| Export boundary | Add `ClipExporterPort` with cache-check, export, and URL methods | Call `R2Storage` / subprocess directly from use case | Preserves hexagonal boundaries and keeps ffmpeg/R2 concerns out of application code. |
| Cache expiry | Bucket lifecycle rule on `exports/` prefix | App-managed expiry timestamps | No storage metadata table exists, and expired exports are derivable artifacts. The repo has no IaC, so lifecycle is an operational prerequisite documented in API/specs. |
| Export mode | Re-encode with `libx264` `veryfast`, not `-c copy` | Stream copy | Locked product decision; only re-encode is frame-accurate for arbitrary timestamps. |

## Data Flow

    POST /clips            POST /clips/{item_id}/export
        │                             │
    get_video_context ────────────────┤
        │                             │
    validate start/end                check cached export key
        │                             │
    INSERT row only                   ├─ hit → presigned URL → 200
                                      └─ miss → ffmpeg from source URL
                                                → upload exports/{item_id}.mp4
                                                → presigned URL → 200

## File Changes

| File | Action | Description |
|---|---|---|
| `src/domain/clip_collections/entities.py` | Modify | Replace file fields with `start_ms`/`end_ms`. |
| `src/application/clip_collections/ports.py` | Modify | Extend `OwnedVideoContext`; change pending item shape; add `ClipExporterPort`. |
| `src/application/clip_collections/use_cases.py` | Modify | Replace filename flow with range validation; add `ExportClipItemUseCase`. |
| `src/application/clip_collections/errors.py` | Modify | Add `INVALID_CLIP_RANGE`; map export failures explicitly (likely 502). |
| `src/infrastructure/clip_collections/postgres_repository.py` | Modify | Persist/read timestamp columns; add item lookup for export. |
| `src/infrastructure/clip_collections/migrations/001_clip_collections_foundation.sql` | Modify | Final destructive schema with `start_ms`/`end_ms` and DB checks. |
| `src/infrastructure/clip_collections/ffmpeg_clip_exporter.py` | Create | ffmpeg + R2 adapter. |
| `src/infrastructure/video/postgres_video_repository.py` | Modify | Return `duration_ms` and `storage_key` in `get_video_context`. |
| `src/infrastructure/storage.py` | Modify | Add read/upload helpers needed by exporter cache check and upload. |
| `src/interfaces/http/routes/clip_collections_router.py` | Modify | Timestamp payloads/responses and new export route. |
| `src/interfaces/http/bootstrap/dependencies.py` | Modify | Wire exporter and export use case. |
| `specs/api/clip-collections.md` | Modify | Breaking request/response contract and export endpoint. |
| `tests/application/clip_collections/test_clip_collection_use_cases.py` | Modify | Validation matrix, NULL-duration case, export hit/miss. |
| `tests/infrastructure/clip_collections/test_postgres_clip_collection_repository.py` | Modify | Timestamp persistence and lookup coverage. |
| `tests/interfaces/http/test_clip_collections_router.py` | Modify | New payloads and export status codes. |
| `tests/interfaces/http/test_main_wiring.py` | Modify | Register export route. |
| `tests/integration/test_clip_collections_integration.py` | Modify | End-to-end timestamp flow and export cache behavior. |
| `Dockerfile` | Modify | Install `ffmpeg`; it is not present today. |

## Interfaces / Contracts

```python
@dataclass(frozen=True)
class PendingClipItem:
    item_id: str
    start_ms: int
    end_ms: int

class ClipExporterPort(ABC):
    def export_exists(self, *, export_key: str) -> bool: ...
    def export_clip(self, *, source_key: str, export_key: str, start_ms: int, end_ms: int) -> None: ...
    def generate_download_url(self, *, export_key: str, expires_in: int = 3600) -> str: ...
```

Adapter flow: presign source with existing storage URL generation, run `ffmpeg -ss <start> -i <url> -t <duration> -c:v libx264 -preset veryfast -c:a aac -movflags +faststart`, write to a temp file, then upload to `exports/` with `video/mp4`.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Range rules, NULL `duration_ms`, cache hit/miss, authz invariants | Fake repos/exporter |
| Integration | Timestamp schema + ordered inserts + export endpoint | Postgres + monkeypatched storage/exporter |
| HTTP | New contracts and 400/403/404/502 mapping | Router tests |
| Infra | ffmpeg command, timeout, cache existence | Mock subprocess and R2 client |

## Migration / Rollout

No data migration required. Rewritten `001` resets clip-collection tables on this unmerged branch. Deploy prerequisites: install ffmpeg in the runtime image and configure an R2 lifecycle rule deleting `exports/` objects after 7 days.

## Open Questions

- [ ] Confirm the desired presigned download URL TTL (design assumes 1 hour).
- [ ] Confirm deployment path does not impose a sub-15s request timeout; otherwise synchronous export needs infrastructure tuning before merge.
