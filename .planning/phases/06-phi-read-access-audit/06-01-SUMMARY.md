---
phase: 06-phi-read-access-audit
plan: 01
subsystem: database
tags: [postgres, audit, alembic, privileges, append-only]
requires:
  - phase: 05
    provides: login_attempts migration (5c1f0e7a9b21), db_roles privilege model
provides:
  - record_access table (append-only for the app role, no foreign keys)
  - RecordAccess model and RECORD_ACCESS_ACTIONS vocabulary
  - APPEND_ONLY_TABLES in scripts/db_roles.py
affects: [06-02, 06-03, 06-04]
tech-stack:
  added: []
  patterns: [REVOKE after blanket GRANT guarded by to_regclass, role-name-validated REVOKE in migration]
key-files:
  created:
    - migrations/versions/20260929_1600_add_record_access.py
    - tests/test_record_access_table.py
  modified:
    - app/models.py
    - scripts/db_roles.py
    - tests/test_db_roles.py
    - tests/conftest.py
    - docker-compose.test.yml
key-decisions:
  - "Append-only enforced by Postgres privileges in both the migration and db_roles.py bootstrap"
  - "scripts/seed.py unchanged: reset already omits record_access and there are no FKs to cascade"
requirements-completed: [AUDIT-01, AUDIT-02]
duration: 20min
completed: 2026-09-30
---

# Phase 6 Plan 01: record_access table Summary

Append-only `record_access` table with Postgres-enforced INSERT/SELECT-only access for the app role, surviving db_roles re-runs, with no FKs so rows outlive records.

## Tasks
1. Contract and table tests (red) - f7d6469
2. Model, migration with guarded REVOKE, db_roles append-only (green) - 367c3ec

Full suite: 145 passed. Migration round-trip (downgrade base, upgrade head) OK. ruff check and mypy app pass.

## Deviations from Plan

None in code. Note: `ruff format --check .` also flags two `.planning/*.md` files (06-PATTERNS.md, 06-RESEARCH.md) when run from a repo mount; they are pre-existing planning docs, out of scope and not fixed. Source, test and script files are clean. Local `ruff`/`mypy` are not installed on the host, so they were run inside the test image with the repo mounted.

## Known Stubs
None.

## Threat Flags
None beyond the plan's threat model (T-06-01..04 mitigated and tested).

## Self-Check: PASSED
