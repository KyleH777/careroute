# Roadmap: CareRoute (Production Readiness)

## Overview

CareRoute is already live on Azure (PRD R1, done 2026-09-24). This milestone makes that deployment trustworthy.

1. Bring the ops docs in line with what Terraform actually built, so every later phase edits accurate runbooks.
2. Take the app off the Postgres admin account before any deploy automation exists.
3. Automate ordered deploys from CI, so every later phase ships the same way.
4. Give logs, metrics and alerts a central, retained home.
5. Harden the internet-facing login.
6. Close the audit gaps so an incident can be scoped to "who read what".
7. Finish with cursor pagination on the worklist.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Ops Docs Match Deployment** - AZURE, RUNBOOK and INCIDENT-RESPONSE describe the Terraform/Key Vault/private-Postgres system as built
- [x] **Phase 2: Least-Privilege Database Roles** - The app runs as a DML-only role; only the migrate job can alter schema; nobody uses the server admin
- [ ] **Phase 3: Automated Ordered Deploys** - Every `main` push deploys via OIDC in ADR-0001 order, and a failed migration leaves the old revision serving
- [ ] **Phase 4: Observability & Central Log Retention** - Request-correlated JSON logs, private `/metrics`, owner alerts, and retained logs in Log Analytics
- [ ] **Phase 5: Login Hardening** - `/auth/token` is rate limited per IP and per account, and every attempt is logged
- [ ] **Phase 6: PHI Read-Access Audit** - The audit trail answers who read which record and records provider assignments, with incident queries to match
- [ ] **Phase 7: Worklist Cursor Pagination** - `/referrals/worklist` pages by cursor with no skips or duplicates

## Phase Details

### Phase 1: Ops Docs Match Deployment
**Goal**: An operator using only the docs can understand, operate and recover the Azure deployment as it actually exists. There is no ad-hoc `az` provisioning, no firewall rules and no hand-typed secrets.
**Depends on**: Nothing (first phase)
**Requirements**: DOCS-01, DOCS-02, DOCS-03
**Success Criteria** (what must be TRUE):
  1. `docs/AZURE.md` walks a reader from backend bootstrap to a live deployment using only Terraform and the Container Apps Jobs. It states centralus, VNet-injected Postgres with no public endpoint or firewall rules, and Key Vault-generated secrets. No `az postgres ... firewall-rule` commands or hand-typed secret steps remain.
  2. Every Azure procedure in `docs/RUNBOOK.md` works against the live deployment. That covers checking health/readiness, reading logs, running migrations via `careroute-migrate`, rotating a secret through Terraform/Key Vault, and restoring through an in-VNet job instead of laptop `psql`. The firewall-rule check is gone.
  3. The credential rotation steps in `docs/INCIDENT-RESPONSE.md` (including the `JWT_SECRET` "invalidate all tokens" lever and the DB password) name the Terraform `random_password` / Key Vault path and the step that makes running revisions pick up the new value.
  4. A reviewer grepping the three docs finds no instruction that contradicts ADR-0006, 0007 or 0008.
**Plans**: 2 plans
- [x] 01-01-PLAN.md — Rewrite docs/AZURE.md as-built (Terraform, centralus, private PG, Key Vault) + fix README's stale Azure/Terraform claims (wave 1)
- [x] 01-02-PLAN.md — Azure paths in RUNBOOK, Terraform/Key Vault rotation in INCIDENT-RESPONSE, cross-doc ADR audit (wave 2)

### Phase 2: Least-Privilege Database Roles
**Goal**: The live API can only read and write data. Only the migrate job can change schema, and the Postgres server admin is not used by any running workload.
**Depends on**: Phase 1 (runbook/AZURE docs are accurate before they are amended for roles)
**Requirements**: DB-01
**Success Criteria** (what must be TRUE):
  1. An in-VNet check against the live database shows API sessions connected as a dedicated app role, not the server admin. That role can SELECT/INSERT/UPDATE/DELETE application tables, and DDL attempts (CREATE/ALTER/DROP) fail with permission denied.
  2. `careroute-migrate` runs `alembic upgrade head` successfully as a separate migration role that owns the schema. Tables created by future migrations are usable by the app role without manual GRANTs (default privileges), and neither role is the server admin.
  3. The new role passwords are Terraform `random_password` values in Key Vault, read by the Container App and jobs via the managed identity (ADR-0008). No human typed or saw them, and role creation runs from inside the VNet (no laptop DB access).
  4. The local Compose stack and CI tests use the same app/migrate role split, so a migration that forgets a grant fails CI before it reaches Azure.
  5. RUNBOOK/AZURE docs describe the roles, which workload uses which, and how to rotate each password.
**Plans**: 3 plans
- [x] 02-01-PLAN.md — Idempotent `scripts/db_roles.py` + Compose/test/CI role split + privilege contract tests; rehearse the upgrade on admin-owned data (wave 1, local only)
- [x] 02-02-PLAN.md — Azure rollout in stages A/B/C: bootstrap job, per-workload identities, per-secret Key Vault RBAC; live evidence for criteria 1-3 (wave 2, checkpoints before push/apply/job runs)
- [x] 02-03-PLAN.md — ADR-0010 + AZURE/RUNBOOK/INCIDENT-RESPONSE/BACKUP-RESTORE/README for roles and rotation (wave 3)

### Phase 3: Automated Ordered Deploys
**Goal**: Merging to `main` puts that commit's image live on Azure with no human steps. The migration always completes before any app revision serves the new code, and CI's Azure access is narrow and credential-free.
**Depends on**: Phase 2 (the role split changes Terraform and migrate-job credentials; automate the final shape, not the interim one)
**Requirements**: DEPLOY-01, DEPLOY-02, DEPLOY-03
**Success Criteria** (what must be TRUE):
  1. After a push to `main` passes CI and publishes the image, the workflow deploys that `sha-` tag without manual action. Afterwards the Container App's active revision and the `careroute-migrate` job both run that exact tag, and the live `/ready` returns 200. Concurrent pushes deploy one at a time (serialized, state-locked).
  2. ADR-0001 order holds and can be shown from the workflow run. The migrate job execution with the new image finishes with exit 0 before any Container App revision with the new image is created. The pipeline does not rely on a single `terraform apply` that changes both the job image and the app image. The ordering hazard in INGEST-CONFLICTS.md is closed by design: for example, a staged apply, keeping the app image out of the first apply, or setting the app image only after migration succeeds.
  3. In a deliberate failing-migration drill, the workflow stops at the migrate step and marks the run failed. The previously active revision keeps serving `/ready` 200, and no new app revision is created.
  4. GitHub holds no Azure client secret or credential. CI signs in via OIDC federation whose subject is restricted to `main` (or a protected `production` environment), so pull-request and fork workflows cannot obtain the identity. Role assignments are scoped to `careroute-rg` plus the state container in `careroute-tfstate-rg`, not the subscription.
  5. The CI identity's ability to read every secret via Terraform state (ADR-0006/0008) is explicitly accepted and documented. The workflow never uploads a `*.tfplan` as an artifact, never prints plan content containing secret values, and the runbook's "who can read secrets" list includes the CI identity.
**Plans**: 3 plans
- [ ] 03-01-PLAN.md — Split app/migrate image vars (required), stable Secrets Officer set, CI identity in its own human-applied root with bounded roles (wave 1)
- [ ] 03-02-PLAN.md — OIDC deploy job: stage-1 apply → migrate exit 0 → stage-2 apply → smoke; serialized; live deploy + failing-migration drill (wave 2)
- [ ] 03-03-PLAN.md — ADR-0011 (accepted secret-read risk) + AZURE/RUNBOOK/INCIDENT-RESPONSE/README (wave 3)

### Phase 4: Observability & Central Log Retention
**Goal**: When something goes wrong, the owner is told, and can trace any request and query application and audit logs centrally long after the container that wrote them is gone.
**Depends on**: Phase 3 (changes ship through the automated pipeline, and alert/infra resources are deployed by it)
**Requirements**: OBS-01, OBS-02, OBS-03, OBS-04
**Success Criteria** (what must be TRUE):
  1. Every API response carries a request-ID header. The container emits one JSON log line per request with that ID, method, path, status and latency, and a Log Analytics query by request ID returns the matching line.
  2. `/metrics` serves Prometheus-format request count/latency by route and status plus DB pool stats inside the environment (and locally). The public Azure URL does not expose it.
  3. In a drill where `/ready` fails (for example the DB is unreachable) or 5xx responses spike, the owner receives an Azure Monitor notification. The alert design works with scale-to-zero left on and stays within the ~$20/month budget.
  4. Application logs and audit events land in Log Analytics with a documented retention period and ingestion cap. They are still queryable after the producing revision/replica is gone, and the runbook contains the queries to find them.
**Plans**: TBD

### Phase 5: Login Hardening
**Goal**: The internet-facing login cannot be brute-forced cheaply, and every attempt leaves evidence an investigator can query.
**Depends on**: Phase 4 (login attempts should also reach central, retained logs)
**Requirements**: LOGIN-01, LOGIN-02
**Success Criteria** (what must be TRUE):
  1. Repeated attempts from one client IP, or against one account from many IPs, get 429 with a `Retry-After` header once the limit is exceeded, and succeed again after the window. Forging an `X-Forwarded-For` header does not bypass the per-IP limit behind Container Apps ingress.
  2. Limits hold across replicas and restarts (scale-to-zero) without adding a paid service beyond the budget.
  3. Below the limit, unknown email, wrong password and inactive account still return the identical 401 with dummy-hash timing equalization (ADR-0003). The existing tests for this keep passing.
  4. Every attempt, success or failure, is recorded in the database with email, client IP, time and outcome, and never the password. The runbook has a query for "failed logins for account X / from IP Y in the last N hours".
**Plans**: TBD

### Phase 6: PHI Read-Access Audit
**Goal**: During an incident, the owner can answer "who read or changed which referral/patient record, and when" from the audit trail.
**Depends on**: Phase 4 (access records need central retention). Independent of Phase 5.
**Requirements**: AUDIT-01, AUDIT-02, AUDIT-03
**Success Criteria** (what must be TRUE):
  1. Every endpoint that returns referral or patient data (single-record and list/worklist) records the authenticated actor (ADR-0004, never client-supplied), the record IDs returned and the time. A test enumerates the app's read routes and fails if one does not audit.
  2. Assigning or changing a referral's provider writes an audit event with actor, old/new provider and time.
  3. `docs/RUNBOOK.md` and `docs/INCIDENT-RESPONSE.md` contain working queries for "who accessed patient/referral X between T1 and T2" and "everything user Y read or changed". The queries run against the live demo and return the expected rows.
  4. INCIDENT-RESPONSE.md no longer lists read access and provider assignment as audit gaps.
**Plans**: TBD

### Phase 7: Worklist Cursor Pagination
**Goal**: API clients can walk the full worklist reliably, page by page, even while referrals change.
**Depends on**: Nothing in this milestone. Placed last as polish; if Phase 6 is done, keeps its read auditing intact.
**Requirements**: API-01
**Success Criteria** (what must be TRUE):
  1. `/referrals/worklist` returns a page of results plus an opaque next cursor. Following cursors until none is returned visits every matching referral exactly once, in a stable order.
  2. Referrals inserted or updated between page requests cause no duplicates or skips of rows that existed when paging began.
  3. A malformed or tampered cursor returns a 4xx validation error, not a 500. The pagination contract (parameters, limits, cursor field) is visible in `/docs`.
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Ops Docs Match Deployment | 2/2 | Complete | 2026-09-25 |
| 2. Least-Privilege Database Roles | 3/3 | Complete | 2026-09-26 |
| 3. Automated Ordered Deploys | 0/3 | Planned | - |
| 4. Observability & Central Log Retention | 0/TBD | Not started | - |
| 5. Login Hardening | 0/TBD | Not started | - |
| 6. PHI Read-Access Audit | 0/TBD | Not started | - |
| 7. Worklist Cursor Pagination | 0/TBD | Not started | - |
