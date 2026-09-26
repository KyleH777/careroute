---
phase: 02-least-privilege-database-roles
plan: 01
status: complete
requirements: [DB-01]
completed: 2026-09-25
---

# 02-01 Summary: local role split

## Built
- `scripts/db_roles.py`: idempotent bootstrap (psycopg only, no app imports). PG16 order from the research: roles + password sync → `GRANT migrate TO CURRENT_USER WITH INHERIT FALSE, SET TRUE` (skipped for superusers) → CONNECT/schema grants → ownership handoff (tables, views, standalone sequences, enum/domain types) → `SET ROLE migrate` → create `alembic_version` if missing → default privileges + grants → `REVOKE ALL ON alembic_version FROM app`.
- Compose (dev + test): `db-roles` one-shot before `migrate`; migrate runs as `careroute_migrate`; api/test run as `careroute_app`. The superuser is used only by db-roles.
- `tests/conftest.py`: `clean_tables` truncates via `OWNER_DATABASE_URL`.
- `tests/test_db_roles.py`: 34 contract checks (identity, DML on every model table, DDL/TRUNCATE denied, no alembic_version writes, not privileged, ownership).
- `scripts/seed.py`: docstring only. `--reset` now runs via `docker compose run --rm migrate ...`.

## Decision: alembic_version gap
db-roles creates `alembic_version` itself (as migrate, using Alembic's exact DDL) before revoking the app's access. That is smaller than reordering services or re-running db-roles after migrate. Alembic reuses the table; the CI round-trip proves it.

## Evidence
- Red: 10 contract failures on the superuser stack. Green: the full suite passes (107), the contract passes after the round-trip (34), and db-roles runs twice with "0 object(s) changed owner".
- CI round-trip (downgrade base → upgrade head) passes as careroute_migrate; no ci.yml change needed.
- Upgrade rehearsal (throwaway project `careroute-upgrade`, old compose → new, superuser-owned seeded DB): 10 objects handed over, 13 relations owned by migrate, `/ready` 200, authenticated worklist 200, API session as careroute_app.
- Restore interplay: `pg_restore --no-owner` → everything superuser-owned and the app denied; one db-roles run → ownership and grants restored, 300 referrals intact, alembic_version still app-unwritable.
- ruff check / format --check: pass (run inside careroute:test; host Python 3.14 can't install the pinned psycopg).

## Deviations
- Removed the duplicate `build:` from the `migrate` service (db-roles builds the shared `careroute:local` image). All services still use the same image.
