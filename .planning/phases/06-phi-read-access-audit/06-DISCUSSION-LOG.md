# Phase 6: PHI Read-Access Audit - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-29
**Phase:** 6-PHI Read-Access Audit
**Areas discussed:** Where access records live, List-read granularity, What counts as a read, Failure + demo volume

---

## Where access records live

| Option | Description | Selected |
|--------|-------------|----------|
| DB table + audit log | New table plus `event=audit` line (Phase 5 pattern) | ✓ |
| Log Analytics only | No migration; 90-day retention, subject to cap, not in backups | |
| DB table only | Queries need an in-VNet job; one tampered DB loses the trail | |

| Option | Description | Selected |
|--------|-------------|----------|
| INSERT + SELECT only | App role can't UPDATE/DELETE audit rows | ✓ |
| Normal DML | Consistent with Phase 2 default privileges | |

| Option | Description | Selected |
|--------|-------------|----------|
| Same new audit table | Assignment as action with old/new provider columns | ✓ |
| Extend referral_events | Add provider columns to the status timeline | |
| You decide | | |

## List-read granularity

| Option | Description | Selected |
|--------|-------------|----------|
| One row per record returned | Plain indexed WHERE for "who accessed X" | ✓ |
| One row per request, ID arrays | Fewer rows; ANY()/GIN queries | |

| Option | Description | Selected |
|--------|-------------|----------|
| referral_id + patient_id | No join needed | ✓ |
| referral_id only | Join referrals at query time | |

| Option | Description | Selected |
|--------|-------------|----------|
| One log line per request with ID lists | Low ingestion; KQL mv-expand | ✓ |
| One log line per record | Simpler KQL, ~20× volume | |

## What counts as a read

| Option | Description | Selected |
|--------|-------------|----------|
| Audit every PHI response | Includes write routes that echo the record | ✓ |
| Only GET routes | Smaller change | |

| Option | Description | Selected |
|--------|-------------|----------|
| All routes, explicit exemption list | New routes fail CI until classified | ✓ |
| Only routes with PHI response models | Can miss dict-returning routes | |

| Option | Description | Selected |
|--------|-------------|----------|
| Only successful reads | 403/404 visible in request log | ✓ |
| Also failed, with outcome column | Spots enumeration | |

## Failure + demo volume

| Option | Description | Selected |
|--------|-------------|----------|
| Fail closed | Same transaction; no audit, no data | ✓ |
| Fail open | Serve and log an error | |

| Option | Description | Selected |
|--------|-------------|----------|
| Keep all, manual prune query | Prune runs as migrate role | ✓ |
| Scheduled prune job | More infra, retention period to choose | |

## Claude's Discretion

Table/column/index names, action vocabulary, audit hook mechanism, route-test detection method, test names, ADR number.

## Deferred Ideas

- Scheduled pruning / formal retention period for access rows.
- Recording denied/not-found attempts with an outcome column.
