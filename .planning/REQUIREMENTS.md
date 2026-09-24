# Requirements: CareRoute

**Defined:** 2026-09-24
**Source:** docs/prd/PRD-production-readiness.md (Draft). Original PRD numbering is shown in brackets.
**Core Value:** On every push to `main`, CI deploys the live demo automatically, in ADR-0001 order. When an incident happens, it can be detected, scoped and contained using docs that match the deployed system, all under ~$20/month.

## Validated (already shipped)

### Live Deployment [R1] (done 2026-09-24)

- [x] **LIVE-01** [R1.1]: The migrate job succeeds on Azure, and `alembic current` equals the repo head
- [x] **LIVE-02** [R1.2]: The seed job succeeds with `--demo-deployment`. Viewer login works with the published password. Clinician/coordinator logins work only with the Key Vault passwords
- [x] **LIVE-03** [R1.3]: The public URL serves `/docs`, and `/health` and `/ready` return 200
- [x] **LIVE-04** [R1.4]: The README shows the live URL and the viewer login

## v1 Requirements (this milestone)

### Operations Docs [R8]

- [ ] **DOCS-01** [R8.1]: `docs/AZURE.md` describes the Terraform deployment as built: centralus, private VNet-injected Postgres with no firewall rules, secrets generated into Key Vault, and migrations/seeding via Container Apps Jobs. The ad-hoc `az` provisioning path and hand-typed secrets are removed
- [ ] **DOCS-02** [R8.2]: The Azure procedures in `docs/RUNBOOK.md` match the deployment: no firewall-rule check, secret rotation through Terraform/Key Vault, and Azure equivalents for logs, migrations and restores (an in-VNet job instead of laptop access)
- [ ] **DOCS-03** [R8.3]: The credential rotation steps in `docs/INCIDENT-RESPONSE.md` point at the Key Vault / Terraform path

### Database Roles [R6]

- [ ] **DB-01** [R6.1]: The app connects as a dedicated Postgres role with DML only. Only the migrate job uses a role that can alter the schema. Neither role is the server admin

### Deploy Automation [R2]

- [ ] **DEPLOY-01** [R2.1]: On `main`, after the image is published, CI runs `terraform plan`/`apply` with the new `sha-` tag, runs the migrate job and waits for success, then rolls the Container App. The order is enforced (ADR-0001)
- [ ] **DEPLOY-02** [R2.2]: CI authenticates to Azure with OIDC workload identity federation. No Azure credentials are stored, and access is scoped to the CareRoute resource groups
- [ ] **DEPLOY-03** [R2.3]: A failed migration stops the deploy and leaves the previous revision serving

### Observability [R3]

- [ ] **OBS-01** [R3.1]: Structured JSON logs include a per-request ID, method, path, status and latency. The request ID is returned in a response header
- [ ] **OBS-02** [R3.2]: Prometheus-format `/metrics` exposes request count/latency by route and status plus DB pool stats. It is not publicly exposed on Azure
- [ ] **OBS-03** [R3.3]: An Azure Monitor alert notifies the owner when `/ready` fails or the 5xx rate spikes
- [ ] **OBS-04** [R3.4]: Application and audit logs are retained centrally (Log Analytics) for a defined period, independent of container lifetime

### Login Hardening [R4]

- [ ] **LOGIN-01** [R4.1]: `/auth/token` is rate limited per client IP and per account, returning 429 with `Retry-After` when a limit is exceeded
- [ ] **LOGIN-02** [R4.2]: Every login attempt (success or failure, email, IP, time) is logged to the database, never including the password

### PHI Access Audit [R5]

- [ ] **AUDIT-01** [R5.1]: Every read endpoint records who read which referral/patient record, and when
- [ ] **AUDIT-02** [R5.2]: Provider assignments are recorded in the audit trail
- [ ] **AUDIT-03** [R5.3]: Runbook and incident queries are updated to use the new logs

### API Polish [R7]

- [ ] **API-01** [R7.1]: `/referrals/worklist` supports cursor pagination

## v2 Requirements

None identified. The PRD lists no deferred-but-planned items. Future candidates go here.

## Out of Scope

| Feature | Reason |
|---------|--------|
| HIPAA certification, BAAs, encryption-at-rest key management beyond Azure defaults | Portfolio demo with synthetic data |
| High availability / multi-region | Cost. Documented as a known limitation |
| Refresh tokens, RS256 | Only one service verifies tokens (ADR-0003). Revisit if that changes |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| LIVE-01 | Pre-milestone | Complete (2026-09-24) |
| LIVE-02 | Pre-milestone | Complete (2026-09-24) |
| LIVE-03 | Pre-milestone | Complete (2026-09-24) |
| LIVE-04 | Pre-milestone | Complete (2026-09-24) |
| DOCS-01 | Phase 1 | Pending |
| DOCS-02 | Phase 1 | Pending |
| DOCS-03 | Phase 1 | Pending |
| DB-01 | Phase 2 | Pending |
| DEPLOY-01 | Phase 3 | Pending |
| DEPLOY-02 | Phase 3 | Pending |
| DEPLOY-03 | Phase 3 | Pending |
| OBS-01 | Phase 4 | Pending |
| OBS-02 | Phase 4 | Pending |
| OBS-03 | Phase 4 | Pending |
| OBS-04 | Phase 4 | Pending |
| LOGIN-01 | Phase 5 | Pending |
| LOGIN-02 | Phase 5 | Pending |
| AUDIT-01 | Phase 6 | Pending |
| AUDIT-02 | Phase 6 | Pending |
| AUDIT-03 | Phase 6 | Pending |
| API-01 | Phase 7 | Pending |

**Coverage:**
- v1 requirements (open): 17 total
- Mapped to phases: 17
- Unmapped: 0
- Validated before the milestone: 4 (LIVE-01..04, not scheduled)

---
*Requirements defined: 2026-09-24*
*Last updated: 2026-09-24 after roadmap creation*
