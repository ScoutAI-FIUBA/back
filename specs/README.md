# Specs

This folder is the source of truth for product intent, API contracts, and architecture decisions.

## Structure

| Folder | Purpose | Typical files |
|---|---|---|
| `prd/` | Product requirement documents (problem, scope, outcomes) | `YYYY-MM-DD-feature-name-prd.md` |
| `api/` | Endpoint contracts for frontend consumption | `resource-action-endpoint.md` |
| `adr/` | Architecture Decision Records (short, focused) | `0001-decision-title.md` |
| `templates/` | Reusable templates for consistency | `prd-template.md`, `endpoint-template.md`, `adr-template.md` |

## Naming conventions

- PRD: `YYYY-MM-DD-<feature>-prd.md`
- API doc: `<domain>-<action>-endpoint.md`
- ADR: `<4-digit-sequence>-<decision-title>.md`

Use kebab-case for file names.

## Workflow

1. Start with a PRD in `prd/`.
2. Define or update endpoint docs in `api/` using the endpoint template.
3. If a technical tradeoff is made, add an ADR in `adr/`.
4. Keep docs and implementation PR in sync.

## Quick start

Copy from `templates/` and fill only what applies. Avoid long prose; prefer concrete examples and explicit acceptance criteria.
