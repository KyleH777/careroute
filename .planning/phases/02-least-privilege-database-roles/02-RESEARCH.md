# Phase 2 Research: Least-Privilege Database Roles

**Date:** 2026-09-25 · **Method:** local throwaway `postgres:16-alpine` spike (free), mimicking Azure's non-superuser CREATEROLE admin. No Azure calls.

## Verified behaviours (PG16)

| # | Question | Result |
|---|---|---|
| 1 | Can a non-superuser CREATEROLE admin `ALTER TABLE ... OWNER TO` a role it just created? | **No**: `must be able to SET ROLE "careroute_migrate"`. Fix: `GRANT careroute_migrate TO <admin> WITH INHERIT FALSE, SET TRUE` (the creator holds ADMIN OPTION in PG16) |
| 2 | Is SET membership enough to transfer ownership? | **No**: `permission denied for schema public` until the new owner has CREATE on `public`. Grant schema CREATE **before** ALTER OWNER |
| 3 | Can the admin run `ALTER DEFAULT PRIVILEGES FOR ROLE careroute_migrate`? | **No** with INHERIT FALSE (`permission denied to change default privileges`). Fix: `SET ROLE careroute_migrate`, then `ALTER DEFAULT PRIVILEGES IN SCHEMA public ...` |
| 4 | Does a table's serial sequence follow the table's ownership? | Yes (owned-by sequences move with the table) |
| 5 | After bootstrap, can migrate CREATE/ALTER tables and CREATE/DROP enum types? | Yes |
| 6 | Does the app get DML on tables created **later** by migrate? | Yes, via default privileges |
| 7 | Is app DDL denied? | Yes: CREATE TABLE (schema), ALTER/DROP (must be owner) |
| 8 | Can the app run `TRUNCATE ... RESTART IDENTITY` with only a TRUNCATE grant? | **No**: `must be owner of sequence`. Test cleanup and `seed --reset` must run as the owner (migrate) |
| 9 | Is `CREATE ROLE` idempotent? | No, so the script must check `pg_roles` first |

The full spike SQL is reproducible from the plan; the throwaway container was removed.

## Codebase facts
- `migrations/env.py` imports `app.config` → the migrate job needs `JWT_SECRET` in production.
- `tests/conftest.py::clean_tables` TRUNCATEs with RESTART IDENTITY on the app engine → needs a separate owner engine.
- `scripts/seed.py`: Azure uses `--demo-deployment` (no reset; DML only). `--reset` is refused outside local/dev/test.
- The runtime image copies `scripts/`, so `db_roles.py` ships in the image; the image has python + psycopg, no psql.
- CI's `test` job uses `docker-compose.test.yml` for pytest and the downgrade base → upgrade head round-trip, so the role split is exercised by changing that file.

## Open risk to probe at execution (free/cheap)
- **Azure database/schema ownership.** It's unknown whether database `careroute` is owned by `careroute_admin`. Probe #2 needs the admin to be able to GRANT on schema `public` (owned by `pg_database_owner`). The first Azure task runs a read-only in-VNet query: `select datdba::regrole from pg_database where datname='careroute'` and `has_schema_privilege('public','CREATE')`. If the admin isn't the DB owner, stop and re-plan.
- azurerm v4 attribute for per-secret RBAC scope: `azurerm_key_vault_secret.resource_versionless_id`. Confirm with `terraform validate`.
