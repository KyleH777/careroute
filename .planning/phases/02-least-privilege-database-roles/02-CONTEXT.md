# Phase 2: Least-Privilege Database Roles - Context

**Gathered:** 2026-09-25
**Status:** Ready for planning
**Source:** plan-phase inline discussion + local PG16 spike (see 02-RESEARCH.md)

<domain>
## Phase Boundary
The API connects as a DML-only role. Only the migrate job can change schema. The server admin is used only by a one-shot bootstrap job. The same role split applies in Compose, the test stack and CI. The docs describe the roles and how to rotate each one.
Out of scope: CI-driven deploys (Phase 3), audit-table immutability, read replicas.
</domain>

<decisions>
## Implementation Decisions

### Roles (locked)
- `careroute_migrate`: LOGIN. Owns every object in schema `public` (tables, sequences, enum types, `alembic_version`). Has CREATE on `public`. Used by: migrate job, test-fixture cleanup (TRUNCATE ... RESTART IDENTITY needs sequence ownership), local `seed --reset`.
- `careroute_app`: LOGIN. USAGE on `public`; SELECT/INSERT/UPDATE/DELETE on all app tables; USAGE/SELECT on sequences; **no** TRUNCATE, no DDL, no privileges on `alembic_version`. Used by: API, seed job (the Azure seed never uses --reset).
- Default privileges are set **as** `careroute_migrate` (via `SET ROLE`), so tables from future migrations are writable by the app with no manual GRANT.
- The server admin (`careroute_admin` in Azure, `careroute` in Compose) is used only by the idempotent bootstrap `scripts/db_roles.py`.

### Bootstrap (locked)
- One script, `scripts/db_roles.py`, runs everywhere: a Compose `db-roles` one-shot service (dev + test + CI) and an Azure Container Apps Job `careroute-db-bootstrap`. Same code path, so CI exercises what Azure runs.
- Idempotent: create the role if missing; always re-sync passwords (this is also the rotation mechanism); transfer ownership of any `public` object not owned by migrate; re-apply grants and default privileges. Safe to run on every `compose up` and after a restore.
- PG16 order (proven in the spike): create roles → `GRANT careroute_migrate TO <admin> WITH INHERIT FALSE, SET TRUE` → `GRANT CREATE, USAGE ON SCHEMA public TO careroute_migrate` → `ALTER ... OWNER TO careroute_migrate` → `SET ROLE careroute_migrate` → grants + `ALTER DEFAULT PRIVILEGES` → `RESET ROLE`.
- Never logs passwords or URLs.

### Azure identities (locked; user chose "split per workload")
- One user-assigned identity per workload: API (existing `careroute-app-id`, kept to avoid replacing the API identity), migrate, seed, db-bootstrap.
- Key Vault access is **per secret** (Key Vault Secrets User scoped to each secret's versionless ID), replacing the vault-wide assignment. The API can read only `database-url` (app role) and `jwt-secret`.
- This amends ADR-0008 (new ADR-0010).

### Rollout (locked)
- Staged by a Terraform variable `db_roles_enabled` (default false). Apply A creates identities, passwords, secrets and the bootstrap job without changing the API or migrate DB credentials. Run bootstrap, then verify. Apply B (flag true, committed) switches `database-url` to the app role and the migrate job to `database-url-migrate`.
- The image must contain `scripts/db_roles.py`, so a CI-published `sha-` tag is required before apply A.

### Cost & outward actions (standing user instruction)
- Nothing that costs money without need. Local Docker work is free and unrestricted.
- **Blocking checkpoints** before: pushing to GitHub `main` (outward-facing; publishes the image), each `terraform apply`, and each Azure job run. Job runs are seconds of consumption; new identities/secrets/job cost ~nothing at rest.

### Claude's Discretion
- Script structure, logging format, test names.
- Secret names beyond those fixed above.
</decisions>

<canonical_refs>
## Canonical References
- `docs/adr/0001-one-shot-migration-before-api.md`: migrate-before-app ordering
- `docs/adr/0007-private-postgres-in-centralus.md`: its "app connects as the server admin" consequence becomes false this phase
- `docs/adr/0008-secrets-generated-into-key-vault.md`: amended by the identity split
- `docs/AZURE.md` → Querying the database from inside the VNet: the job-override rules (--image, --env-vars, "-cCODE") from the Phase 1 rehearsal
- `.planning/phases/01-ops-docs-match-deployment/01-VERIFICATION.md`: rehearsal findings
- `infra/keyvault.tf`, `infra/containerapps.tf`, `infra/database.tf`
- `docker-compose.yml`, `docker-compose.test.yml`, `.github/workflows/ci.yml`, `tests/conftest.py`, `scripts/seed.py`
</canonical_refs>

<specifics>
- `seed.py --reset` uses TRUNCATE ... RESTART IDENTITY, so it must run as `careroute_migrate`. Local docs change from `docker compose exec api python scripts/seed.py --reset` to a migrate-role invocation.
- `pg_restore --no-owner` as the Compose superuser leaves restored objects owned by that superuser. Re-running `db-roles` fixes ownership, so BACKUP-RESTORE must say so.
- The migrate job still needs `JWT_SECRET`, because `migrations/env.py` imports `app.config`, which refuses the dev default when APP_ENV=production.
</specifics>

<deferred>
- Making `referral_events` INSERT/SELECT-only for the app (DB-enforced audit immutability). A good follow-up, but it changes app behaviour; better in Phase 6.
- Revoking CONNECT on the database from PUBLIC.
</deferred>

---
*Phase: 02-least-privilege-database-roles · Context gathered 2026-09-25*
