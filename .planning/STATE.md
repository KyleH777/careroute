# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-24)

**Core value:** On every push to `main`, CI deploys the live demo automatically, in ADR-0001 order. When an incident happens, it can be detected, scoped and contained using docs that match the deployed system, all under ~$20/month.
**Current focus:** Phase 3 - Automated Ordered Deploys

## Current Position

Phase: 3 of 7 (Automated Ordered Deploys)
Plan: 0 of TBD in current phase
Status: Ready to plan
Last activity: 2026-09-26 - Phase 2 complete: least-privilege roles + per-workload identities live (stages A/B/C), docs + ADR-0010

Progress: [███░░░░░░░] 29%

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
- [Phase 2]: Split identities per workload + per-secret Key Vault RBAC (user choice); ADR-0010 amends ADR-0008
- [Phase 2]: PG16 bootstrap order: GRANT migrate TO admin WITH SET TRUE → schema CREATE → ALTER OWNER → SET ROLE migrate for grants/default privileges
- [Phase 1]: Container Apps job overrides replace the whole container: always pass --image, --env-vars (secretref) and --command. Phase 3 CI must do the same
- [Phase 1]: Deploy/rollback edits `image` in variables.tf (not `-var`) so later applies can't silently roll back
- [Roadmap]: R3 observability/retention before R4/R5, so login and read-access events have a central home

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 3] Hazard: a single `terraform apply` that updates both the migrate-job image and the app image would roll the app before migration (violates ADR-0001). The pipeline must stage this.
- [Phase 3] Hazard: the CI OIDC identity can read all secrets via state. Needs a narrow federated subject, no tfplan artifacts, no plan output in logs.
- [Phase 4] Alerting vs scale-to-zero: an external availability probe on `/ready` wakes the app and may keep a replica warm (cost). Research alert signal options (metric/log alerts vs availability tests) against the ~$20/month budget. The existing workspace has a 0.5 GB/day cap and 30-day retention.
- [Phase 5] The rate limiter must see the real client IP behind Container Apps ingress and share state across replicas without a paid cache (Postgres-backed is a candidate).
- [General] `.planning/` is public. Never paste secrets, Key Vault values or plan output into planning artifacts.

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-09-25
Stopped at: Phase 2 complete. Next: `/gsd:plan-phase 3`. Phase 3 note: CI deploy identity needs to start jobs; per ADR-0010 that is effectively migrate/admin DB access, so scope it to the migrate job only (never db-bootstrap).
Resume file: None
