# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-24)

**Core value:** On every push to `main`, CI deploys the live demo automatically, in ADR-0001 order. When an incident happens, it can be detected, scoped and contained using docs that match the deployed system, all under ~$20/month.
**Current focus:** Phase 4 - Observability & Central Log Retention

## Current Position

Phase: 4 of 7 (Observability & Central Log Retention)
Plan: 0 of 3 in current phase
Status: Ready to execute
Last activity: 2026-09-28 - Phase 4 planned (3 plans): log/metric alerts, 90-day retention, metrics on unmapped port

Progress: [████░░░░░░] 43%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: -
- Trend: -

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions (ADR-0001..0009 locked).
Recent decisions affecting current work:

- [Roadmap]: R8 docs first, so later phases amend accurate runbooks
- [Roadmap]: R6 DB roles before R2 CI deploy, so the pipeline automates the final credential/Terraform shape
- [Phase 1]: Azure restore = PITR to new server; cutover and in-VNet logical dumps are documented gaps
- [Phase 4]: No availability probe (cost/scale-to-zero); alerts = 5xx + /ready 503 log-search + is_db_alive metric; email to owner via TF_VAR_alert_email; retention 90 d
- [Phase 3]: CI runs Terraform (user choice over image-only model); accepted risk: CI reads all secrets; bounded by separate CI RG, constrained RBAC Admin, container-scoped state access
- [Phase 2]: Split identities per workload + per-secret Key Vault RBAC (user choice); ADR-0010 amends ADR-0008
- [Phase 2]: PG16 bootstrap order: GRANT migrate TO admin WITH SET TRUE → schema CREATE → ALTER OWNER → SET ROLE migrate for grants/default privileges
- [Phase 1]: Container Apps job overrides replace the whole container: always pass --image, --env-vars (secretref) and --command. Phase 3 CI must do the same
- [Phase 1]: Deploy/rollback edits `image` in variables.tf (not `-var`) so later applies can't silently roll back
- [Roadmap]: R3 observability/retention before R4/R5, so login and read-access events have a central home

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 5] The rate limiter must see the real client IP behind Container Apps ingress and share state across replicas without a paid cache (Postgres-backed is a candidate).
- [General] `.planning/` is public. Never paste secrets, Key Vault values or plan output into planning artifacts.

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-09-25
Stopped at: Phase 4 planned. Next: `/gsd:execute-phase 4`
Resume file: None
