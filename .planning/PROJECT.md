# CareRoute

## What This Is

CareRoute is a healthcare referral-routing API (FastAPI + Postgres 16) built as a portfolio project that demonstrates production engineering practice. It already ships JWT auth with viewer/clinician/coordinator roles, an audit trail with token-derived actors, Alembic migrations, a backup/restore drill, a hardened multi-arch image on GHCR, CI (ruff/mypy, 73 tests against real Postgres, Trivy gate), a runbook, an incident-response process and 9 ADRs. It runs live on Azure Container Apps with private Postgres and Key Vault, provisioned by Terraform (applied 2026-09-24): https://careroute-api.yellowglacier-b6e91890.centralus.azurecontainerapps.io

This milestone ("production readiness", from `docs/prd/PRD-production-readiness.md`) makes the live demo something an engineer would trust. Deploys become automated and ordered. The service becomes observable. The internet-facing login resists abuse. The audit trail can answer "who saw what" during an incident.

## Core Value

On every push to `main`, CI deploys the live demo automatically, in ADR-0001 order. When an incident happens, it can be detected (alert), scoped (who read or changed what, from centrally retained logs) and contained, using operations docs that match the deployed system. All of this stays under ~$20/month.

## Requirements

### Validated

<!-- Shipped and confirmed. -->

- ✓ JWT auth (HS256, 60 min) with viewer/clinician/coordinator roles and a per-request user re-check (ADR-0003)
- ✓ Audit actor taken from the authenticated identity for status changes (ADR-0004)
- ✓ Alembic migrations run by a one-shot migrate step that gates API startup (ADR-0001)
- ✓ Separate liveness (`/health`) and readiness (`/ready`) probes (ADR-0002)
- ✓ Hardened multi-arch image (Docker Hardened Images) published to GHCR, with a Trivy gate in CI (ADR-0005)
- ✓ CI: ruff, mypy, 73 tests against real Postgres, migration round-trip check
- ✓ Backup/restore drill, runbook, incident-response process
- ✓ Terraform remote state in an Entra-only storage account (ADR-0006)
- ✓ Private VNet-injected Postgres 16 in centralus (ADR-0007)
- ✓ Terraform-generated secrets in Key Vault, read via managed identity (ADR-0008)
- ✓ Public demo with a read-only viewer login only (ADR-0009)
- ✓ LIVE-01..04 (PRD R1): Azure deployment verified live end to end on 2026-09-24. Migrate job at repo head, seed job with `--demo-deployment`, `/docs` + `/health` + `/ready` serving, README shows the live URL and viewer login.

### Active

<!-- This milestone. Full detail and IDs in REQUIREMENTS.md. -->

- [ ] Operations docs (AZURE, RUNBOOK, INCIDENT-RESPONSE) describe the system as deployed (PRD R8)
- [ ] App and migrate job use separate, non-admin Postgres roles (PRD R6)
- [ ] CI deploys automatically on `main` in ADR-0001 order, using OIDC (PRD R2)
- [ ] Structured logs, `/metrics`, alerts and central log retention (PRD R3)
- [ ] `/auth/token` rate limiting and login-attempt logging (PRD R4)
- [ ] PHI read-access and provider-assignment audit logging (PRD R5)
- [ ] Cursor pagination on `/referrals/worklist` (PRD R7)

### Out of Scope

- HIPAA certification, BAAs, encryption-at-rest key management beyond Azure defaults: a portfolio demo with synthetic data, not a covered entity
- High availability / multi-region: cost. Documented as a known limitation
- Refresh tokens and RS256: not needed while a single service verifies tokens. Revisit if another service must verify them (ADR-0003)

## Context

- **Runtime:** Azure Container Apps (Consumption workload profile, scale-to-zero) in centralus. Postgres Flexible Server 16 (B1ms), VNet-injected. RBAC-mode Key Vault with a user-assigned managed identity. Log Analytics workspace `careroute-logs` (30-day retention, 0.5 GB/day ingestion cap) already backs the Container Apps environment.
- **Infra as code:** Terraform in `infra/` with azurerm remote state in `careroute-tfstate-rg` (eastus, Entra-only). The app lives in `careroute-rg`. Jobs `careroute-migrate` and `careroute-seed` are manual-trigger Container Apps Jobs. The 2026-09-24 apply was run from a laptop.
- **CI:** GitHub Actions `.github/workflows/ci.yml` runs lint, type-check, tests, Trivy and the multi-arch GHCR publish (`sha-` tags). There is no deploy step yet.
- **Known gaps closed by this milestone:** the app connects as the Postgres server admin (ADR-0007). Reads and provider assignments are not audited (ADR-0004). `/auth/token` has no rate limit or attempt logging (ADR-0003, ADR-0009). There is no alerting. The ops docs still describe an older ad-hoc `az` provisioning path with firewall rules and hand-typed secrets.
- **Public planning:** `.planning/` is committed to the public GitHub repo. Nothing in it may contain secrets, plan output or Key Vault values.
- **Source docs:** ADRs in `docs/adr/`, PRD in `docs/prd/PRD-production-readiness.md`. Ingest intel in `.planning/intel/`.

## Constraints

- **Budget**: under ~$20/month for the whole demo, and scale-to-zero stays on. Every new Azure resource (alerts, availability checks, log ingestion) must fit.
- **Region**: centralus for the app and database (ADR-0007). Terraform state stays in eastus.
- **Quality bar**: every change keeps CI green, and the runbook stays accurate for whatever that change deploys.
- **Deploy order**: the migration must exit 0 before any app revision serves the new code (ADR-0001). CI must not rely on a single `terraform apply` that changes both the job image and the app image.
- **Secret exposure**: the CI OIDC identity can read every secret through Terraform state (ADR-0006/0008). Scope its federated subject narrowly (the `main` branch or a protected environment). Never upload or log `*.tfplan` files or plan output containing secrets.
- **Secrets**: any new secret (for example DB role passwords) is a Terraform `random_password` written to Key Vault and read via managed identity (ADR-0008).
- **Auth behavior**: login keeps the identical 401 for unknown email, wrong password and inactive account, with dummy-hash timing equalization (ADR-0003), including after rate limiting is added.
- **No laptop DB access**: Postgres is private. Any DB operation on Azure (role bootstrap, restore, ad-hoc queries) runs as a job or container inside the VNet (ADR-0007).

## Key Decisions

<decisions>
Locked decisions from Accepted ADRs. Planners must not revisit these without a new ADR.

| ID | Decision | Source | Status |
|----|----------|--------|--------|
| ADR-0001 | Migrations run in a dedicated one-shot process that must exit 0 before the API starts (Compose `migrate` service locally; `careroute-migrate` Container Apps Job on Azure). Migrations are baked into the image. | docs/adr/0001-one-shot-migration-before-api.md | Locked |
| ADR-0002 | `/health` = liveness, never touches the DB. `/ready` = readiness, runs `SELECT 1`, returns 503 when the DB is unreachable without leaking the error. | docs/adr/0002-separate-liveness-and-readiness.md | Locked |
| ADR-0003 | OAuth2 password flow issues 60-min HS256 JWTs. argon2id hashes. Role and active status re-loaded from the DB per request. Identical 401 plus dummy-hash timing for all login failures. Refuses the dev `JWT_SECRET` outside local/dev/test. | docs/adr/0003-jwt-with-per-request-user-check.md | Locked |
| ADR-0004 | Audit actor = authenticated user's email. Request bodies carry no `actor`, and a spoofed one is ignored. | docs/adr/0004-audit-actor-from-token.md | Locked |
| ADR-0005 | Docker Hardened Images base (`dhi.io/python:3.12-debian13[-dev]`), non-root, no shell, multi-arch, Trivy gate on fixable HIGH/CRITICAL. | docs/adr/0005-docker-hardened-images.md | Locked |
| ADR-0006 | Terraform state lives in a separate Entra-only storage account in `careroute-tfstate-rg` (versioning, soft delete, CanNotDelete lock). Anyone with blob read on state can read secrets. | docs/adr/0006-terraform-state-backend.md | Locked |
| ADR-0007 | Postgres 16 Flexible Server is VNet-injected with no public access, TLS required, in centralus. Container Apps env is in the same VNet. | docs/adr/0007-private-postgres-in-centralus.md | Locked |
| ADR-0008 | All secrets are Terraform `random_password` values in an RBAC Key Vault, read only via a user-assigned managed identity (versionless refs). Plan files embed secrets and are git-ignored. | docs/adr/0008-secrets-generated-into-key-vault.md | Locked |
| ADR-0009 | Public demo publishes only the viewer password. Clinician/coordinator passwords are private (Key Vault, 16+ chars). `--demo-deployment` is required outside local/dev/test, and `--reset` is refused there. | docs/adr/0009-read-only-public-demo.md | Locked |
</decisions>

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| `.planning/` committed publicly | Planning is part of the portfolio story | Pending |
| Least-privilege DB roles (R6) land before CI deploy automation (R2) | R6 changes Terraform and migrate-job credentials. Automating deploys first would mean automating a pipeline that is about to change | Pending |
| Observability and log retention (R3) land before login hardening (R4) and PHI read logging (R5) | R4/R5 events need a central, retained home to be useful in an incident | Pending |

---
*Last updated: 2026-09-24 after new-project ingest (ADRs 0001-0009 + production-readiness PRD)*
