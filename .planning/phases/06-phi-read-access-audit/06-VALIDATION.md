---
phase: 6
slug: phi-read-access-audit
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-09-29
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.4 + httpx TestClient, ephemeral Postgres 16 with role split |
| **Config file** | `pyproject.toml` (`testpaths = ["tests"]`); fixtures in `tests/conftest.py` |
| **Quick run command** | `docker compose -p careroute-test -f docker-compose.test.yml run --rm test pytest -x -q tests/test_access_audit.py tests/test_audit_route_coverage.py tests/test_db_roles.py` |
| **Full suite command** | `docker compose -p careroute-test -f docker-compose.test.yml run --rm test` (then `... down -v`), plus `ruff check . && ruff format --check . && mypy app` |
| **Estimated runtime** | ~90 seconds |

---

## Sampling Rate

- **After every task commit:** Run the quick run command
- **After every plan wave:** Run the full suite command + ruff + mypy
- **Before `/gsd:verify-work`:** Full suite must be green; live-demo query check recorded (see Manual-Only)
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

*Filled in by the planner/executor per task. Seeded from RESEARCH.md requirement → test map:*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-T1 | 01 | 1 | AUDIT-01/02 | T-06-01, T-06-02, T-06-04 | Append-only contract written first (red) | contract | `pytest tests/test_db_roles.py tests/test_record_access_table.py` | ❌ W0 (created here) | ⬜ pending |
| 06-01-T2 | 01 | 1 | AUDIT-01/02 | T-06-01..04 | App role INSERT/SELECT only on `record_access`, survives `db_roles` re-run; rows survive record delete and `seed --reset` | contract + CI round-trip | full test stack + `alembic downgrade base && upgrade head` | ✅ after T1 | ⬜ pending |
| 06-02-T1 | 02 | 2 | AUDIT-01/02 | T-06-07..11 | Behaviour, fail-closed, spoof, no-PHI, route-enumeration tests (red) | integration + unit | `pytest tests/test_access_audit.py tests/test_audit_route_coverage.py` | ❌ W0 (created here) | ⬜ pending |
| 06-02-T2 | 02 | 2 | AUDIT-01/02 | T-06-07..11 | Six PHI routes audit in-transaction; assign records old/new provider; limit 1..100 | integration | full test stack + ruff + mypy | ✅ after T1 | ⬜ pending |
| 06-03-T1 | 03 | 2 | AUDIT-03 | T-06-14, T-06-15, T-06-18 | Runbook SQL executes via `text()` like `sql()`, time-windowed; prune owner-only | integration + host grep | `pytest tests/test_runbook_record_access.py` + verbatim check | ❌ W0 (created here) | ⬜ pending |
| 06-03-T2 | 03 | 2 | AUDIT-03 | T-06-16 | Gap text removed; ADR-0014; retention 90 d | doc grep | DOCS-OK grep chain | n/a | ⬜ pending |
| 06-04-T1 | 04 | 3 | all | T-06-19, T-06-20 | Pre-push gate identical to CI; no token-shaped strings | full suite | full test stack + round-trip + ruff + mypy | ✅ | ⬜ pending |
| 06-04-T2 | 04 | 3 | all | T-06-19, T-06-21 | Owner approves push + drill | checkpoint | n/a (human) | n/a | ⬜ pending |
| 06-04-T3 | 04 | 3 | AUDIT-01/02/03 | T-06-20, T-06-22, T-06-23 | Live SQL/KQL return drill rows; live append-only check | manual/live | evidence grep on 06-04-SUMMARY.md | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_access_audit.py` — behavioural tests for AUDIT-01/02/03
- [ ] `tests/test_audit_route_coverage.py` — route enumeration test for AUDIT-01
- [ ] `tests/conftest.py` — add `record_access` to `clean_tables`; row-read helper fixture
- [ ] `tests/test_db_roles.py` — exclude append-only tables from DML-on-every-table test; add append-only contract test

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Runbook SQL + KQL queries return expected rows against the live demo | AUDIT-03 | Requires deployed Azure environment and Log Analytics ingestion (minutes of lag) | After CI deploy: exercise worklist/detail/assign as a demo user, wait for ingestion, run RUNBOOK `sql` helper queries and `az monitor log-analytics query` KQL; record output in VERIFICATION.md |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
