# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-24)

**Core value:** On every push to `main`, CI deploys the live demo automatically, in ADR-0001 order. When an incident happens, it can be detected, scoped and contained using docs that match the deployed system, all under ~$20/month.
**Current focus:** Phase 3 - Automated Ordered Deploys

## Current Position

Phase: 3 of 7 (Automated Ordered Deploys)
Plan: 1 of 3 complete; 03-02 paused after first deploy attempt
Status: Paused (user request)
Last activity: 2026-09-26 - First automated deploy (run 36261898752) failed at OIDC login; Azure untouched

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
- [Phase 3]: CI runs Terraform (user choice over image-only model); accepted risk: CI reads all secrets; bounded by separate CI RG, constrained RBAC Admin, container-scoped state access
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
Stopped at: 03-02 Task 4. Pushed c3bb05b; CI lint/test/image green (image sha-c3bb05b published); deploy failed at `azure/login`: AADSTS700213. Cause: the repo's OIDC subject uses GitHub's immutable-ID format `repo:KyleH777@88053223/careroute@1383757448:environment:production`, but infra/ci's federated credential expects `repo:KyleH777/careroute:environment:production`. No Terraform/job ran; the API is still on sha-da96d74.
Resume: (1) change infra/ci subject to the ID form (make var github_repo -> github_subject_repo = "KyleH777@88053223/careroute@1383757448"), human-apply infra/ci (1 in-place/replace of the federated credential); (2) re-run the deploy: `gh run rerun 36261898752 --failed -R KyleH777/careroute`; (3) evidence for criteria 1/2/4; (4) drill checkpoint; (5) 03-03 docs (note the subject format in ADR-0011/RUNBOOK "CI is red": AADSTS700213 = subject mismatch).
Resume file: None
