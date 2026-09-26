# ADR-0010: Least-privilege database roles and per-workload identities

- **Status:** Accepted (amends ADR-0008)
- **Date:** 2026-09-26

## Context

The API connected to Postgres as the server admin, so an injection bug or a stolen connection string meant full control of the schema. Separately, one managed identity could read every Key Vault secret. Once the vault also held admin and migration credentials, a compromised API could fetch them and undo any database-level separation.

## Decision

Two Postgres roles, created and maintained by `scripts/db_roles.py`:

- `careroute_migrate` owns every object in schema `public` and runs Alembic.
- `careroute_app` has SELECT/INSERT/UPDATE/DELETE only: no DDL, no TRUNCATE, no access to `alembic_version`. Default privileges, set as the owner, make tables from future migrations usable with no manual GRANT.

The server admin is used only by the `careroute-db-bootstrap` job, which runs that script. The script is idempotent: it creates missing roles, re-syncs both passwords from Key Vault (this is how they rotate), hands any stray objects to the owner and re-applies grants. Compose and CI run the same script before migrations, and `tests/test_db_roles.py` pins the privilege contract.

Each workload has its own user-assigned identity (API `careroute-app-id`; `careroute-migrate-id`, `careroute-seed-id`, `careroute-dbbootstrap-id`). Each gets Key Vault Secrets User **per secret**, only on the secrets it needs. The API can read `database-url` (app role) and `jwt-secret`, and nothing else.

Rolled out in stages (`db_roles_enabled`, `legacy_vault_wide_app_access`) so that no single apply switched credentials and permissions at once.

## Consequences

- A compromised API can read and change data, but can't alter the schema, truncate tables, or read the migrate or admin credentials.
- Rotating `pg_app` or `pg_migrate` takes two steps: `terraform apply -replace=...`, then run db-bootstrap straight away (Key Vault holds the new password before the database does).
- `TRUNCATE ... RESTART IDENTITY` needs sequence ownership, so test cleanup and local `seed --reset` run as the migrate role.
- `pg_restore --no-owner` leaves restored objects owned by whoever restored them. Run db-roles afterwards.
- Permission to start `careroute-db-bootstrap` is effectively admin on the database (a job's command can be overridden to use its secrets). The same goes for migrate and the owner role.
- The migrate job still reads `jwt-secret`, because `migrations/env.py` imports the app config, which requires it in production.
