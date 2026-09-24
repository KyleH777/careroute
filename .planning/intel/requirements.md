# Requirements (from PRDs)

Synthesized by gsd-doc-synthesizer on 2026-09-24, mode `new`.
One PRD ingested: /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/prd/PRD-production-readiness.md (Status: Draft, 2026-09-24, "input to the next GSD milestone").
Original PRD numbering (R1..R8, R1.1..) is preserved alongside derived REQ IDs. Acceptance criteria are verbatim-faithful; no merging was needed (single PRD, no competing variants).

PRD goal (source: PRD-production-readiness.md): CareRoute runs live on Azure as a portfolio demo that a reviewer can use and an engineer would trust: deployments automated and ordered, service observable, internet-facing login resists abuse, audit trail can answer "who saw what" during an incident.

PRD current state (source: PRD-production-readiness.md): API, CI (lint, test, Trivy, multi-arch GHCR publish), hardened image, runbook and incident process are done. Azure Terraform (Container Apps + private Postgres + Key Vault, 27 resources) applied from a laptop on 2026-09-24. Migrations and seeding run as manual-trigger jobs. Live at https://careroute-api.yellowglacier-b6e91890.centralus.azurecontainerapps.io.

---

## REQ-verified-live-deployment (PRD R1) -- STATUS: DONE 2026-09-24
- source: /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/prd/PRD-production-readiness.md
- description: The Azure deployment is verified live end to end.
- acceptance:
  - R1.1 Migrate job succeeds; `alembic current` on Azure equals repo head.
  - R1.2 Seed job succeeds with `--demo-deployment`; viewer login works with the published password; clinician/coordinator only with Key Vault passwords.
  - R1.3 Public URL serves `/docs`, `/health` 200, `/ready` 200.
  - R1.4 README shows the live URL and the viewer login.
- scope: Azure deploy verification
- related decisions: ADR-0001, ADR-0002, ADR-0009

## REQ-automated-ordered-deploys (PRD R2) -- open
- source: /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/prd/PRD-production-readiness.md
- description: Deploys run automatically from CI in the order required by ADR-0001.
- acceptance:
  - R2.1 On `main`, after the image is published: `terraform plan`/`apply` with the new `sha-` tag, run the migrate job and wait for success, then roll the Container App. Order is enforced (ADR-0001).
  - R2.2 CI authenticates to Azure with OIDC workload identity federation, with no stored Azure credentials, scoped to the CareRoute resource groups.
  - R2.3 A failed migration stops the deploy and leaves the previous revision serving.
- scope: GitHub Actions deploy pipeline, GHCR, OIDC, Terraform, Container Apps Jobs
- related decisions: ADR-0001 (implements its "CI deploy step should enforce the order"), ADR-0006, ADR-0008
- planning note: see INGEST-CONFLICTS.md INFO entries on apply-vs-roll ordering and CI access to the state backend.

## REQ-observability (PRD R3) -- open
- source: /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/prd/PRD-production-readiness.md
- description: The service is observable via structured logs, metrics, alerts and central log retention.
- acceptance:
  - R3.1 Structured JSON logs with a per-request ID, method, path, status and latency; request ID returned in a response header.
  - R3.2 Prometheus-format `/metrics` (request count/latency by route and status, DB pool stats); not publicly exposed on Azure.
  - R3.3 An Azure Monitor alert when `/ready` fails or 5xx rate spikes, notifying the owner. Addresses "no monitoring or alerting".
  - R3.4 Application and audit logs retained centrally (Log Analytics) for a defined period, independent of container lifetime. Addresses "no central log retention".
- scope: logging middleware, `/metrics`, Azure Monitor, Log Analytics
- related decisions: ADR-0002 (`/ready` semantics the alert depends on)

## REQ-login-hardening (PRD R4) -- open
- source: /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/prd/PRD-production-readiness.md
- description: The internet-facing `/auth/token` endpoint resists abuse and every attempt is logged.
- acceptance:
  - R4.1 Rate limit `/auth/token` per client IP and per account; 429 with `Retry-After` when exceeded.
  - R4.2 Log every login attempt (success/failure, email, IP, time) to the database, without passwords.
- scope: `/auth/token`, rate limiting, login-attempt table
- related decisions: ADR-0003 (lists these as not yet done; must preserve identical-401 and timing-equalization behavior), ADR-0009 (rate limiting open work)

## REQ-phi-read-access-logging (PRD R5) -- open
- source: /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/prd/PRD-production-readiness.md
- description: The audit trail can answer who read which PHI record and records provider assignments.
- acceptance:
  - R5.1 Record who read which referral/patient record, and when, for every read endpoint.
  - R5.2 Record provider assignments in the audit trail.
  - R5.3 Runbook/incident queries updated to use the new logs.
- scope: read endpoints, audit trail, runbook/incident docs
- related decisions: ADR-0004 (closes its listed gaps; actor must come from the authenticated identity)

## REQ-least-privilege-db-roles (PRD R6) -- open
- source: /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/prd/PRD-production-readiness.md
- description: The app and the migrate job use separate, non-admin Postgres roles.
- acceptance:
  - R6.1 The app connects as a dedicated Postgres role with DML only; only the migrate job uses a role that can alter schema. Neither is the server admin.
- scope: Postgres roles, connection config, Key Vault secrets for new role passwords
- related decisions: ADR-0007 (closes its open work), ADR-0008 (new role passwords must be Terraform-generated into Key Vault), ADR-0001 (migrate job is the only schema-altering process)

## REQ-worklist-cursor-pagination (PRD R7) -- open
- source: /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/prd/PRD-production-readiness.md
- description: API polish.
- acceptance:
  - R7.1 Cursor pagination on `/referrals/worklist`.
- scope: `/referrals/worklist`

## REQ-ops-docs-match-deployment (PRD R8) -- open
- source: /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/prd/PRD-production-readiness.md
- description: Operations docs describe the system as actually deployed. (The target docs were excluded from this ingest per the manifest; their stale Azure content is what this requirement tracks.)
- acceptance:
  - R8.1 `docs/AZURE.md` describes the Terraform deployment as built: centralus, private (VNet-injected) Postgres with no firewall rules, secrets generated into Key Vault, migrations/seeding via Container Apps Jobs. Remove the ad-hoc `az` provisioning path and hand-typed secrets.
  - R8.2 `docs/RUNBOOK.md` Azure procedures match: no firewall-rule check; secret rotation through Terraform/Key Vault; Azure equivalents for logs, migrations and restores (in-VNet job instead of laptop access).
  - R8.3 `docs/INCIDENT-RESPONSE.md` credential rotation steps point at the Key Vault / Terraform path.
- scope: docs/AZURE.md, docs/RUNBOOK.md, docs/INCIDENT-RESPONSE.md
- related decisions: ADR-0006, ADR-0007, ADR-0008, ADR-0001

---

## Out of scope (source: PRD-production-readiness.md)
- HIPAA certification, BAAs, encryption-at-rest key management beyond Azure defaults.
- High availability / multi-region (cost; documented as a known limitation).
- Refresh tokens and RS256 (revisit if another service must verify tokens). Consistent with ADR-0003 "not yet done" list.

## PRD constraints
Recorded in /Users/kyleharrington/Desktop/AI/Docker/CareRoute/.planning/intel/constraints.md.
