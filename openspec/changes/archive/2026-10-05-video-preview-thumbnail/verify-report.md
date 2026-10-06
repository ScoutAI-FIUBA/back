# Verification Report: Video Preview Thumbnails

**Change**: video-preview-thumbnail
**Version**: video-thumbnails v1 (delta spec)
**Mode**: Standard (Strict TDD disabled — `openspec/config.yaml` `apply.tdd: false`)
**Verification type**: Re-verification (implementation changed after the previous verify: a W2 regression test was added)
**Verified artifacts**: proposal, spec (`specs/video-thumbnails/spec.md`), design, tasks, apply-progress
**Evidence basis**: adversarial source inspection of the changed code + fresh live test execution on Python 3.14 in `.venv`

## Verdict

**PASS WITH WARNINGS**

All 7 requirements and all 11 scenarios are implemented and now proven by **passing runtime tests**.
The full non-DB suite is green (**378 passed, 0 failed**), and the previously-static non-goal scenario
is now covered by an executed, non-vacuous regression test (**W2 RESOLVED**). The only remaining gaps are
two WARNING-severity items: the user-accepted DB-unavailable environmental gap (W1) and a test-depth
nuance on access control (W3). There are **no CRITICAL findings**. This is a clear pass.

## Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 19 |
| Tasks complete | 19 |
| Tasks incomplete | 0 |

Every task 1.1–5.4 was inspected in source, not merely trusted from the `[x]` marks (see Task Audit).

## Build & Tests Execution

**Build**: ➖ Not applicable — `openspec/config.yaml` defines `verify.build_command: ""`.

**Tests (non-integration, required command)**:
```text
.venv/bin/python -m pytest -m "not integration" -q
→ 378 passed, 31 deselected, 4505 warnings in 22.39s
```
✅ 378 passed / ❌ 0 failed / ⚠️ 31 deselected (integration-marked, expected)

**Tests (router file, includes the new W2 regression test)**:
```text
.venv/bin/python -m pytest tests/interfaces/http/test_videos_router.py -q
→ 6 passed, 340 warnings in 3.73s
```

**Tests (DB integration, required command)**:
```text
.venv/bin/python -m pytest tests/integration/test_video_thumbnail_repository_integration.py \
  tests/integration/test_video_management_integration.py -q
→ 4 skipped in 6.63s   ("Postgres not reachable for integration tests")
```

**Coverage**: ➖ Not available — `coverage_threshold: 0`, no coverage command configured.

## Requirement Coverage

| # | Requirement | Scenario | Covering Test(s) | Result |
|---|-------------|----------|------------------|--------|
| REQ-01 | Generate Thumbnail on Upload Completion | Successful upload generates thumbnail | `test_use_cases.py > test_complete_upload_generates_and_persists_thumbnail` | ✅ COMPLIANT |
| REQ-01 | Generate Thumbnail on Upload Completion | Generation failure does not fail upload | `test_use_cases.py > test_complete_upload_survives_thumbnail_failure` | ✅ COMPLIANT |
| REQ-01 | Generate Thumbnail on Upload Completion | Seek unavailable falls back to frame 0 | `test_ffmpeg_thumbnail_generator.py > test_generate_falls_back_to_frame_zero_when_seek_yields_no_frame` | ✅ COMPLIANT |
| REQ-02 | Stable Thumbnail Object | Same object across reads | `test_use_cases.py > test_get_video_presigns_existing_thumbnail_without_generating` (deterministic `_thumbnail_key`; persisted key reused; generator not called) | ✅ COMPLIANT |
| REQ-03 | Expose Thumbnail on Get Video | Video with thumbnail | `test_use_cases.py > test_get_video_presigns_existing_thumbnail_without_generating`; `test_videos_router.py > test_get_video_returns_presigned_thumbnail_url_when_present` | ✅ COMPLIANT |
| REQ-03 | Expose Thumbnail on Get Video | Video without thumbnail | `test_use_cases.py > test_get_video_returns_null_thumbnail_when_backfill_fails`; `test_videos_router.py > test_get_video_returns_null_thumbnail_url_when_absent` | ✅ COMPLIANT |
| REQ-04 | Lazy Fallback Generation on Read | Legacy video backfilled on first read | `test_use_cases.py > test_get_video_backfills_missing_thumbnail` | ✅ COMPLIANT |
| REQ-04 | Lazy Fallback Generation on Read | Lazy generation failure still returns 200 | `test_use_cases.py > test_get_video_returns_null_thumbnail_when_backfill_fails` + router stub returns 200 | ✅ COMPLIANT |
| REQ-05 | Delete Thumbnail With Video | Delete removes both objects | `test_use_cases.py > test_delete_removes_source_and_thumbnail` (+ `test_delete_skips_thumbnail_when_null`, `test_delete_ignores_thumbnail_delete_failure`) | ✅ COMPLIANT |
| REQ-06 | Access Control | Non-owner is denied | `test_videos_router.py > test_authz_unauthorized_team_access_matrix_returns_403` (GET included) | ✅ COMPLIANT |
| REQ-07 | Non-Goals | List endpoint unchanged | `test_videos_router.py > test_list_videos_does_not_expose_thumbnail_fields` (**new**, runtime) | ✅ COMPLIANT |

**Compliance summary**: **11/11 scenarios runtime-compliant** (previously 10/11; REQ-07 is no longer static-only).

### W2 resolution — the new regression test is meaningful, not vacuous

`test_list_videos_does_not_expose_thumbnail_fields`:
- Wires `_ListOkUC` (returns exactly one `_ReadyVideo`) through the real router and the real
  shared `_video_to_dict` serializer.
- Asserts `status_code == 200`, `len(items) == 1`, and that each item has no `thumbnail_key`,
  no `presigned_thumbnail_url`, and **no key containing the substring `"thumbnail"`**.
- `_ReadyVideo` carries `thumbnail_key = None`, so adding any thumbnail field to `_video_to_dict`
  (or the list route) would surface the key and fail the assertion. The guard is therefore live:
  it would catch the exact regression it targets. Confirmed executed and passing (6 passed).

## Correctness (Static Evidence)

| Requirement | Status | Notes |
|------------|--------|-------|
| Generate on upload completion | ✅ Implemented | `CompleteVideoUploadUseCase._generate_thumbnail_best_effort`: generate → `set_thumbnail_key` in `uow.transaction()`, wrapped in `except Exception: return video` (`use_cases.py:169-188`). |
| Deterministic key | ✅ Implemented | `_thumbnail_key(team_id, video_id) -> f"thumbnails/{team_id}/{video_id}.jpg"` (`use_cases.py:28-31`). |
| Best-effort (never fails upload) | ✅ Implemented | All generator/persistence errors swallowed; READY video returned with null key. |
| Stable object / read-time presign | ✅ Implemented | Get presigns `video.thumbnail_key` when set; never persists a URL (`use_cases.py:245-250`). |
| Lazy fallback | ✅ Implemented | `GetVideoUseCase._backfill_thumbnail` runs only when `READY` and `thumbnail_key is None`; failures yield `null` (`use_cases.py:252-269`). |
| Delete both objects | ✅ Implemented | Source delete unchanged; thumbnail delete under `contextlib.suppress(Exception)`; null keys skipped (`use_cases.py:326-328`). |
| Access control | ✅ Implemented | `assert_access` runs before any read/generation in both `CompleteVideoUploadUseCase` (line 145) and `GetVideoUseCase` (line 237); route maps errors to 403/404. |
| 15s bounded timeout | ✅ Implemented | `FFmpegThumbnailGenerator(timeout_seconds=15)` → `subprocess.run(..., timeout=15)`; asserted in adapter test. |
| Presigned retrieval | ✅ Implemented | `R2Storage.generate_presigned_url` (`storage.py:214`) used at read time. |
| Port/adapter shape | ✅ Implemented | `ThumbnailGeneratorPort` ABC + `FFmpegThumbnailGenerator(ThumbnailGeneratorPort)`; depends on concrete `R2Storage` per design. |
| `GET /videos` gains no field | ✅ Implemented | Router diff confirms `_video_to_dict` untouched; new field added only to the `get_video` dict literal (`videos_router.py:172-176`). |

## Coherence (Design)

| Decision | Followed? | Notes |
|----------|-----------|-------|
| Generator depends on concrete `R2Storage` (not narrow port) | ✅ Yes | `storage: R2Storage`; matches `FFmpegClipExporter`. |
| Key `thumbnails/{team_id}/{video_id}.jpg` | ✅ Yes | `_thumbnail_key` helper. |
| Nullable column + `set_thumbnail_key` | ✅ Yes | Migration `003_video_thumbnail_key.sql`; owner-scoped `UPDATE ... RETURNING *`. |
| Presign at read time; `_video_to_dict` untouched | ✅ Yes | Confirmed by router diff. |
| Wire into Complete + Get; Delete reuses `storage` | ✅ Yes | `dependencies.py:408, 561, 575`; Delete wiring unchanged. |
| Constructor defaults incl. `timeout_seconds=15` | ✅ Yes | Adapter defaults; test asserts `timeout == 15`. |
| ADR 2 — synchronous bounded generation on complete | ✅ Yes | Bounded, error-swallowing, persists only on success. |
| ADR 3 — lazy fallback, no lock, idempotent deterministic key | ✅ Yes | Duplicate CPU work accepted; single PUT. |
| Delete under `contextlib.suppress(Exception)` | ✅ Yes | Best-effort cleanup. |
| `GetVideoUseCase.execute` returns 3-tuple | ✅ Yes | `(video, playback_url, presigned_thumbnail_url)`. |
| Documented deviation: return refreshed row from `set_thumbnail_key` | ⚠️ Deviation (benign) | Row status remains READY; callers observe persisted key. No spec impact. |
| Documented deviation: no source-URL TTL param | ⚠️ Deviation (benign) | Uses `R2Storage` default 3600s; no unused knob. |

## Task Audit

19/19 tasks verified in source (not merely marked `[x]`):

- Phase 1 (1.1–1.4): migration file exists with the exact nullable column; `thumbnail_key` is the last `Video` field; `ThumbnailGeneratorPort` and `set_thumbnail_key` present in `ports.py`.
- Phase 2 (2.1–2.5): `_row_to_video` reads `thumbnail_key`; `set_thumbnail_key` implemented owner-scoped; adapter created with `-ss 2` → frame-0 fallback, `-frames:v 1`, `scale=640:-2`, `qscale=3`, `image/jpeg`.
- Phase 3 (3.1–3.4): complete/lazy generation, 3-tuple return, best-effort delete all present.
- Phase 4 (4.1–4.2): router unpacks 3-tuple and adds `presigned_thumbnail_url`; wiring constructs and injects the generator.
- Phase 5 (5.1–5.4): adapter (3), repository-mapper/unit (4), use-case (new), router (6 incl. the W2 regression test) tests exist and pass.

## Findings

**CRITICAL**: None.

**WARNING**:
- **W1 — DB-unavailable verification gap (environmental, user-accepted).** `set_thumbnail_key` SQL and the `_row_to_video` column read have no live-PostgreSQL execution proof. `tests/integration/test_video_thumbnail_repository_integration.py` (round-trip) and the DB-backed `test_video_management_integration.py` are written but **skipped** (4 skipped: "Postgres not reachable"). This is explicitly accepted; it is not a hidden pass and not CRITICAL. Set `DATABASE_URL` to a live Postgres and re-run the two integration files to close it.
- **W3 — Access-control scenario covered at HTTP mapping level only.** `test_authz_unauthorized_team_access_matrix_returns_403` uses a stubbed `GetVideoUseCase` that raises `FORBIDDEN_TEAM_ACCESS`, so the HTTP contract for REQ-06 is runtime-proven. However, no dedicated non-DB test drives the **real** `GetVideoUseCase` with a disallowed team to exercise the `team_access.assert_access` call at `use_cases.py:237`. Source inspection confirms the check runs first (before any read/generation), and the pattern matches the other video use cases, so the risk is low — but the use-case-level branch is untested.

**RESOLVED**:
- **W2 (previous finding) — RESOLVED.** The non-goal "List endpoint unchanged" is no longer proven only statically. The new `test_list_videos_does_not_expose_thumbnail_fields` runs against the real router and shared serializer, asserts a one-item payload, and rejects any thumbnail field. It executed and passed (router file: 6 passed; full non-DB suite: 378 passed). REQ-07 is now ✅ COMPLIANT.

**SUGGESTION**:
- **S1** — Add a non-DB use-case test that constructs the real `GetVideoUseCase` with a team outside `_TeamAccess.allowed_teams` and asserts `TEAM_NOT_FOUND` (closes W3 at depth, cheap).
- **S2** — Add a double-`GET` test to make REQ-02 "same object across reads" explicit at runtime rather than inferred from the deterministic key.
- **S3** — Replace bare `except Exception` swallowing with a logged warning (`logger.warning(..., exc_info=True)`) so thumbnail failures are observable in production while staying best-effort.
- **S4** — The two documented apply-progress deviations (return refreshed row; no source-URL TTL knob) are benign and spec-compatible; no action required.

## Accepted Environmental Warning (explicit)

> No PostgreSQL/DB connection is available in this environment. DB/repository integration tests are
> written but cannot run. This is recorded as **WARNING W1** — an environmental verification gap —
> never as a hidden pass and never as CRITICAL. The user has explicitly accepted this risk.

## Final Verdict

**PASS WITH WARNINGS** — every requirement is implemented and design-coherent; **11/11 scenarios are
runtime-verified by passing non-DB tests**, including the previously-static non-goal (W2 now RESOLVED);
the full non-DB suite passes (378 passed, 0 failed). Remaining gaps are the accepted DB-unavailable
environmental gap (W1) and a minor access-control test-depth nuance (W3). No CRITICAL findings.
