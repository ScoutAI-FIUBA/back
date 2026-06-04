# ADR Template

- **ADR**: `0002-video-delete-compensation-policy`
- **Date**: 2026-05-27
- **Status**: Accepted

## Context

Deleting a video touches Postgres metadata and Cloudflare R2 objects, but there is no distributed transaction across both systems. A hard failure on storage deletion can leave API behavior inconsistent and make retries ambiguous.

## Decision

Use compensating deletion:
- First mark video as deleted in DB (`status=DELETED`, `deleted_at` set).
- Then attempt object deletion in R2.
- If R2 deletion fails, keep the video hidden from API responses and return a deterministic accepted response with compensation pending.
- Emit structured log/event for retry reconciliation.

## Consequences

- Positive: API consistency is preserved; deleted videos do not reappear.
- Negative: Temporary orphaned objects may remain in R2 until compensation succeeds.
- Follow-up: Implement retry worker + observability (pending deletion metrics/alerts) for compensation backlog.
