---
phase: 06-phi-read-access-audit
plan: 03
subsystem: docs
tags: [audit, runbook, incident-response, adr, kql]
requires:
  - phase: 06-01
    provides: record_access table and RecordAccess model
provides:
  - RUNBOOK Record access section (SQL, KQL, migrate-role prune)
  - tests/test_runbook_record_access.py executing the runbook SQL
  - ADR-0014 and INCIDENT-RESPONSE scope queries with audit gaps removed
affects: [06-04]
key-files:
  created:
    - tests/test_runbook_record_access.py
    - docs/adr/0014-phi-access-audit.md
  modified:
    - docs/RUNBOOK.md
    - docs/INCIDENT-RESPONSE.md
    - docs/AZURE.md
    - docs/adr/README.md
    - docs/adr/0004-audit-actor-from-token.md
    - docs/adr/0010-per-workload-identities-and-db-roles.md
key-decisions:
  - "Every runbook record_access query is time-windowed because seed --reset restarts IDs"
  - "Prune runs only as the migrate role via careroute-migrate; sql() is refused by design"
  - "Log Analytics retention documented as 90 days (infra/containerapps.tf)"
requirements-completed: [AUDIT-03]
completed: 2026-09-30
---

# Phase 6 Plan 03: Runbook queries and audit docs Summary

Tested, time-windowed SQL and KQL for record_access in the RUNBOOK, an owner-only prune, ADR-0014, and INCIDENT-RESPONSE with the read and assignment gaps removed.

## Tasks
1. Runbook SQL/KQL executed by tests - df7dd93
2. ADR-0014, INCIDENT-RESPONSE, AZURE retention, ADR cross-references - 8a8a68d

Verification: tests/test_runbook_record_access.py 3 passed in the test stack (project careroute-test-0603); host-side check confirms every RUNBOOK_SQL template is verbatim in docs/RUNBOOK.md; DOCS-OK check passes; ruff check and format clean on the new test.

## Deviations from Plan

None. The plan's prune template is shown in the runbook both as a migrate-job override and as a local psql command.

## Known Stubs
None.

## Threat Flags
None. Docs use only example addresses.

## Notes
The KQL depends on plan 06-02's audit line fields (patient_ids, referral_ids, old/new provider); it was not run against live logs here (plan 04).

## Self-Check: PASSED
