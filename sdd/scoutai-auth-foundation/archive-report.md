# Archive Report — scoutai-auth-foundation

**Date**: 2026-05-17
**Project**: back
**Mode Requested**: hybrid
**Archive Executor**: sdd-archive

## Artifact Traceability (Engram)

- Proposal: `sdd/scoutai-auth-foundation/proposal` → Observation **#141**
- Spec: `sdd/scoutai-auth-foundation/spec` → Observation **#142**
- Design: `sdd/scoutai-auth-foundation/design` → Observation **#144**
- Tasks: `sdd/scoutai-auth-foundation/tasks` → Observation **#146**
- Verify report: `sdd/scoutai-auth-foundation/verify-report` → Observation **#151**

## Local Artifact Consolidation

The repository does not contain an `openspec/` tree. Local artifacts for this change are consolidated under `specs/prd/` and `sdd/`:

- `specs/prd/scoutai-auth-foundation-proposal.md`
- `specs/prd/scoutai-auth-foundation-spec.md`
- `specs/prd/scoutai-auth-foundation-design.md`
- `specs/prd/scoutai-auth-foundation-tasks.md`
- `specs/prd/scoutai-auth-foundation-apply-progress.md`
- `specs/prd/scoutai-auth-foundation-verify-report.md`
- `specs/prd/scoutai-auth-foundation-verify-report-hotfix-logout-cookie.md`
- `sdd/scoutai-auth-foundation/apply-progress.md`

No `openspec/changes/{change}` folder exists to move. For this repository layout, this archive report is the local closure artifact.

## Implemented vs Pending

### Implemented
- Auth foundation delivered with hexagonal split (domain/application/infrastructure/interface).
- Endpoints implemented and verified: `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me`.
- Token strategy implemented: JWT access (15m) + opaque refresh (7d), strict rotation, reuse detection, logout invalidation.
- Postgres repositories and constraints covered by tests.
- Targeted hotfix for logout cookie applied and re-verified.

### Pending / Follow-up
- Add explicit HTTP integration test for `login -> logout -> refresh` asserting `401` + error envelope (currently covered at use-case level, not full transport flow).

## Residual Risks

1. **Transport-level regression gap**: missing one end-to-end HTTP auth-session sequence test may allow router/cookie wiring regressions to slip despite use-case coverage.
2. **Process mismatch risk**: requested hybrid mode expects `openspec/` merge+move semantics, but this repo currently uses `specs/prd` + `sdd` structure; without a normalized archive convention, future automation may drift.

## Completion Verdict

SDD cycle is functionally complete for this change with **PASS WITH WARNINGS** verification status and no CRITICAL findings.
