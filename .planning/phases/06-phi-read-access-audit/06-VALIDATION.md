---
phase: 6
slug: phi-read-access-audit
status: draft
nyquist_compliant: false
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
| TBD | TBD | TBD | AUDIT-01 | Actor spoofing | Actor taken only from verified token; client `actor` ignored | integration | `pytest tests/test_access_audit.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | AUDIT-01 | Audit write failure | Audit insert failure → 5xx, no PHI body | integration | `pytest tests/test_access_audit.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | AUDIT-01 | PHI in logs | Log lines carry IDs/actions only (sentinel PHI scan) | integration | `pytest tests/test_access_audit.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | AUDIT-01 | — | Every non-exempt route is audited (enumeration) | unit | `pytest tests/test_audit_route_coverage.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | AUDIT-02 | — | Assign/reassign records old/new provider + actor + time | integration | `pytest tests/test_access_audit.py -k assign` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | AUDIT-01 | Track erasure | App role lacks UPDATE/DELETE/TRUNCATE on `record_access`, survives `db_roles` re-run | contract | `pytest tests/test_db_roles.py` | ✅ (update) | ⬜ pending |
| TBD | TBD | TBD | AUDIT-03 | — | Runbook SQL returns expected rows against test DB | integration | `pytest tests/test_access_audit.py -k runbook` | ❌ W0 | ⬜ pending |

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
