# Archive Report: Video Preview Thumbnails

**Change**: `video-preview-thumbnail`
**Archived**: 2026-10-05
**Archive folder**: `openspec/changes/archive/2026-10-05-video-preview-thumbnail/`
**Capability**: `video-thumbnails` (NEW — additive)
**Inherited verdict**: PASS WITH WARNINGS (0 CRITICAL)

## Summary

Video preview thumbnails shipped as a new capability: one JPEG per uploaded video, generated
best-effort at upload completion and lazily on first read, exposed as a presigned
`presigned_thumbnail_url` on `GET /videos/{id}`. The delta was synced into the canonical spec
space and the completed change moved into the archive. The change is **additive and
non-destructive** — a new nullable `thumbnail_key` column and a brand-new capability. No
destructive delta was merged, satisfying the `openspec/config.yaml` `archive` rule
("Warn before merging destructive deltas").

## Quick Path

1. Canonical spec created: `openspec/specs/video-thumbnails/spec.md`.
2. Change folder moved: `openspec/changes/video-preview-thumbnail/` →
   `openspec/changes/archive/2026-10-05-video-preview-thumbnail/`.
3. Engram archive report persisted: `sdd/video-preview-thumbnail/archive-report`.

## Spec Sync

| Domain | Main spec before | Action | Details |
|--------|------------------|--------|---------|
| `video-thumbnails` | (none) | Created | 7 requirements / 11 scenarios. The delta spec is a full spec for a new capability, so it was copied verbatim. |

No `MODIFIED`, `REMOVED`, or `RENAMED` requirements. No destructive merge.
`openspec/specs/clip-collections/spec.md` was left untouched.

### Destructive-delta check (explicit)

| Delta kind | Present? | Action |
|------------|----------|--------|
| ADDED requirements | Yes (all 7) | Written as a new capability spec |
| MODIFIED requirements | No | — |
| REMOVED requirements | No | — |
| RENAMED requirements | No | — |

Result: **non-destructive / additive**. No warning-triggered confirmation was required.

## Archive Contents

| Artifact | Status |
|----------|--------|
| `proposal.md` | ✅ |
| `specs/video-thumbnails/spec.md` | ✅ |
| `design.md` | ✅ |
| `tasks.md` | ✅ 19/19 complete (`[x]`, no stale unchecked tasks) |
| `apply-progress.md` | ✅ |
| `verify-report.md` | ✅ PASS WITH WARNINGS, 0 CRITICAL |
| `archive-report.md` | ✅ (this file) |

## Traceability (Engram observations)

| Artifact | Filesystem | Engram |
|----------|------------|--------|
| proposal | `.../proposal.md` | #205 |
| spec | `.../specs/video-thumbnails/spec.md` | #206 |
| design | `.../design.md` | #207 |
| tasks | `.../tasks.md` | #208 |
| apply-progress | `.../apply-progress.md` | #209 |
| verify-report | `.../verify-report.md` | #210 |

## Task Completion Gate

**PASSED.** The persisted tasks artifact (Engram #208 and filesystem `tasks.md`) shows 19/19
implementation tasks checked `[x]`. `apply-progress` (#209) reports 19/19 complete, and
`verify-report` (#210) audited all 19 tasks in source. No stale unchecked tasks were present, so
no archive-time reconciliation was required.

## Verification Summary

- Verdict: **PASS WITH WARNINGS** — 11/11 scenarios runtime-compliant.
- CRITICAL findings: **0** (archive blocker check passed).
- Non-DB suite: **378 passed, 0 failed**; router file 6 passed.
- **W1 (accepted, environmental)**: no live PostgreSQL available → DB integration tests are
  written but skipped. The user explicitly accepted this risk. Not a blocker.
- **W3 (minor)**: access-control proven at the HTTP mapping level only; the real
  `GetVideoUseCase` denial branch is untested (source-verified). Low risk.
- **W2**: RESOLVED by the new runtime regression test covering the list non-goal.

## Source of Truth Updated

The following canonical spec now reflects the shipped behavior:

- `openspec/specs/video-thumbnails/spec.md`

## Risks Carried Forward

- **W1** closes by pointing `DATABASE_URL` at a live Postgres and re-running
  `tests/integration/test_video_thumbnail_repository_integration.py`.
- Non-blocking follow-ups from verify: S1 real use-case access-denial test; S2 double-GET test for
  REQ-02; S3 log instead of a bare `except`.

## Checklist

- [x] Main specs updated correctly (new capability created)
- [x] Change folder moved to archive
- [x] Archive contains all artifacts
- [x] Archived `tasks.md` has no unchecked implementation tasks
- [x] Active changes directory no longer contains this change

---

**SDD cycle complete** — the change was planned, implemented, verified, and archived.
