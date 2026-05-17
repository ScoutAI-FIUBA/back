# Project Map (Hexagonal Architecture)

This repository is split by responsibility so business rules stay isolated from frameworks and vendors.

## Quick navigation

| Section | Purpose | Change here when... |
|---|---|---|
| `src/domain/` | Entities, value objects, domain rules | A business rule or core model changes |
| `src/application/` | Use cases and input/output ports | You add/modify a workflow or boundary contract |
| `src/infrastructure/` | DB/queue/filesystem/external concrete adapters | A technology integration changes |
| `src/interfaces/http/` | FastAPI routing, request/response mapping | API endpoints or HTTP contracts change |
| `src/ai/` | AI service ports and concrete model adapters | Model provider logic, prompts, or inference adapters change |
| `specs/` | Documentation workflow (`prd/`, `api/`, `adr/`, `templates/`) | Product requirements, API contracts, or architecture decisions change |
| `ops/engram/` | Shared Engram decision exports (`engram-export-YYYYMMDD*.json`) | Team needs synced decision snapshots for planning/review |
| `.opencode/` | Project-specific AI skills and conventions | Team adds reusable delivery/quality skills |

## Common cross-cutting skills

Apply these across all sections:

- **Hexagonal boundaries first**: dependencies point inward (interfaces/adapters depend on application/domain, not inverse).
- **Keep domain pure**: no FastAPI, DB SDK, or model-vendor SDK imports in `domain`.
- **Explicit contracts**: define ports in `application` (or `ai` when AI-specific), implement in adapters.
- **Thin transport layer**: HTTP layer maps data and delegates to use cases.
- **Single responsibility modules**: one reason to change per file/class/module.

## Section-specific skills

| Section | Primary skills |
|---|---|
| `src/domain/` | Ubiquitous language, invariants, side-effect-free logic |
| `src/application/` | Use-case orchestration, port design, transactional boundaries |
| `src/infrastructure/` | Adapter implementation, resilience/retry, provider-specific mapping |
| `src/interfaces/http/` | FastAPI routing, validation, serialization, status-code semantics |
| `src/ai/` | Prompt boundary design, model abstraction, provider swap-ability |
| `specs/` | PRD-first planning, frontend-facing API contracts, ADR traceability |
| `ops/engram/` | Shared decision snapshots, milestone exports, review context |
| `.opencode/` | Team AI workflow rules, quality gates, reusable automations |

## Practical change flow

1. Start from `specs/prd/` using `specs/templates/prd-template.md` (what/why).
2. Define frontend-facing endpoint contracts in `specs/api/` using `specs/templates/endpoint-template.md`.
3. Record technical tradeoffs in `specs/adr/` using `specs/templates/adr-template.md`.
4. Encode business intent in `domain` and `application` (contracts).
5. Implement technology details in `infrastructure` / `ai` adapters.
6. Expose behavior via `interfaces/http`.
