# Engram Exports (Shared Team Decisions)

## Purpose

This folder stores shared Engram decision snapshots so project decisions are visible to all team members in the repository.

## What to export

Export high-value knowledge that helps execution and reviews:

- Decisions
- Architecture choices
- Reusable patterns
- Bugfix learnings

Do not export secrets, credentials, tokens, or private personal data.

## Naming convention

Use:

- `engram-export-YYYYMMDD.json`
- Optional time suffix for multiple exports in one day: `engram-export-YYYYMMDD-HHMM.json`

Examples:

- `engram-export-20260517.json`
- `engram-export-20260517-1530.json`

## How and when to export

Export after major milestones, for example:

- End of a feature batch
- Architecture changes
- Incident/bugfix retrospectives
- Before opening large PRs

Keep snapshots concise and focused on decisions that others must know.

## Team workflow consumption

- Treat the latest export as a decision context source during planning, implementation, and review.
- Reference relevant items in PR descriptions when they influence tradeoffs.
- Update exports when decisions change, so historical context remains traceable.

## Git policy

Exports in this folder are versionable by default so the whole team has the same decision history.
Before commit, review and redact any sensitive information.

## Current exports

- `engram-export-20260517.json`
