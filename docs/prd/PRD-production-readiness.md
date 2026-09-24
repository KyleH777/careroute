# PRD: Production readiness for the live demo

- **Status:** Draft, input to the next GSD milestone
- **Date:** 2026-09-24
- **Context:** [ADRs](../adr/README.md), [Runbook](../RUNBOOK.md),
  [Incident response](../INCIDENT-RESPONSE.md) (its "Known limitations" table
  is the source of most requirements below)

## Goal

CareRoute runs live on Azure as a portfolio demo that a reviewer can use and an
engineer would trust: deployments are automated and ordered, the service is
observable, the internet-facing login resists abuse, and the audit trail can
answer "who saw what" during an incident.

## Current state

- API, CI (lint → test → Trivy → multi-arch GHCR publish), hardened image,
  runbook and incident process: done.
- Azure: Terraform for Container Apps + private Postgres + Key Vault applied
  from a laptop on 2026-09-24 (27 resources; see ADR-0006..0009). Migrations
  and seeding run as manual-trigger jobs. Live at https://careroute-api.yellowglacier-b6e91890.centralus.azurecontainerapps.io.

## Requirements

### R1: Verified live deployment (done 2026-09-24)
- R1.1 Migrate job succeeds; `alembic current` on Azure equals repo head.
- R1.2 Seed job succeeds with `--demo-deployment`; viewer login works with the
  published password; clinician/coordinator only with Key Vault passwords.
- R1.3 Public URL serves `/docs`, `/health` 200, `/ready` 200.
- R1.4 README shows the live URL and the viewer login.

### R2: Automated, ordered deploys from CI
- R2.1 On `main`, after the image is published: `terraform plan`/`apply`
  with the new `sha-` tag, run the migrate job and wait for success, then
  roll the Container App. Order is enforced (ADR-0001).
- R2.2 CI authenticates to Azure with OIDC workload identity federation,
  with no stored Azure credentials, scoped to the CareRoute resource groups.
- R2.3 A failed migration stops the deploy and leaves the previous revision
  serving.

### R3: Observability
- R3.1 Structured JSON logs with a per-request ID, method, path, status and
  latency; request ID returned in a response header.
- R3.2 Prometheus-format `/metrics` (request count/latency by route and
  status, DB pool stats); not publicly exposed on Azure.
- R3.3 An Azure Monitor alert when `/ready` fails or 5xx rate spikes,
  notifying the owner. Addresses "no monitoring or alerting".
- R3.4 Application and audit logs retained centrally (Log Analytics) for a
  defined period, independent of container lifetime. Addresses "no central
  log retention" (incident evidence currently disappears with the container).

### R4: Login hardening
- R4.1 Rate limit `/auth/token` per client IP and per account; 429 with
  `Retry-After` when exceeded.
- R4.2 Log every login attempt (success/failure, email, IP, time) to the
  database, without passwords.

### R5: Access logging for PHI reads
- R5.1 Record who read which referral/patient record, and when, for every
  read endpoint.
- R5.2 Record provider assignments in the audit trail.
- R5.3 Runbook/incident queries updated to use the new logs.

### R6: Least-privilege database access
- R6.1 The app connects as a dedicated Postgres role with DML only; only the
  migrate job uses a role that can alter schema. Neither is the server admin.

### R7: API polish
- R7.1 Cursor pagination on `/referrals/worklist`.

### R8: Operations docs match the deployed system
- R8.1 `docs/AZURE.md` describes the Terraform deployment as built:
  centralus, private (VNet-injected) Postgres with no firewall rules,
  secrets generated into Key Vault, migrations/seeding via Container Apps
  Jobs. Remove the ad-hoc `az` provisioning path and hand-typed secrets.
- R8.2 `docs/RUNBOOK.md` Azure procedures match: no firewall-rule check;
  secret rotation through Terraform/Key Vault; Azure equivalents for
  logs, migrations and restores (in-VNet job instead of laptop access).
- R8.3 `docs/INCIDENT-RESPONSE.md` credential rotation steps point at the
  Key Vault / Terraform path.

## Out of scope

- HIPAA certification, BAAs, encryption-at-rest key management beyond
  Azure defaults.
- High availability / multi-region (cost; documented as a known limitation).
- Refresh tokens and RS256 (revisit if another service must verify tokens).

## Constraints

- Budget: keep the demo under ~$20/month; scale-to-zero stays on.
- Region: centralus (ADR-0007).
- Every change keeps CI green and the runbook accurate.
