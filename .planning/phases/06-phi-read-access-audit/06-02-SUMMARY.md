---
phase: 06-phi-read-access-audit
plan: 02
subsystem: api
tags: [audit, phi, fastapi, fail-closed, route-enumeration]
requires:
  - phase: 06-01
    provides: record_access table, RecordAccess model, RECORD_ACCESS_ACTIONS
provides:
  - app/access_audit.py (ACTIONS, audited, stage, emit)
  - six audited PHI routes writing record_access rows in the route transaction
  - route-enumeration test guarding future routes
affects: [06-03, 06-04]
tech-stack:
  added: []
  patterns: [stage-before-commit fail-closed audit, __audit_action__ route marker, module-attribute calls for monkeypatching]
key-files:
  created:
    - app/access_audit.py
    - tests/test_access_audit.py
    - tests/test_audit_route_coverage.py
  modified:
    - app/main.py
    - tests/test_observability.py
key-decisions:
  - "stage() runs before session.commit() and exceptions are not caught, so audit failure means 500 and rollback"
  - "create_patient uses flush() so the 409 path stages nothing; single commit follows staging"
  - "Worklist limit bounded 1..100 via Query (422 outside)"
requirements-completed: [AUDIT-01, AUDIT-02]
duration: 25min
completed: 2026-09-30
---

# Phase 6 Plan 02: Route auditing Summary

All six PHI routes now write one record_access row per record (actor from the token only) in the route's own transaction and emit one ID-only audit log line after commit; assignments record old/new provider; a route-enumeration test fails CI for any unaudited, non-exempt route.

## Tasks
1. Behavioural, fail-closed and route-coverage tests (red) - 1354370
2. access_audit module and route wiring (green) - 6fd7e3c (includes ruff format of app/main.py)

Full suite: 167 passed. ruff check, ruff format --check (app, tests, scripts, migrations) and mypy app pass (run in the test image with the repo mounted).

## Deviations from Plan

None - plan executed as written. Worktree base was corrected with the prescribed `git reset --hard` at start (merge-base differed).

Minor: test_observability status-change test now asserts `[ln["action"] ...] == ["referral.status_changed"]` rather than `len(lines) == 1`, to satisfy the acceptance grep. Pre-existing `len(lines) == 1` remains in the access-log test, which is unrelated.

## Known Stubs
None.

## Threat Flags
None beyond the plan's threat model (T-06-07..11 mitigated and tested).

## Self-Check: PASSED
