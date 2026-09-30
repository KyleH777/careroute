# ADR-0014: PHI access audit in an append-only table and the log

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

Only status changes were recorded (ADR-0004). Reads and provider assignments were not, so if an account was compromised nobody could say which patients it had viewed, and the public viewer account (ADR-0009) could read PHI-shaped data with no trace. Incident response could not scope an exposure.

## Decision

- **A table and a log line.** `record_access` holds one row per PHI access, and each audited request also emits one ID-only `audit` line to Log Analytics (ADR-0012). The table answers queries; the log copy is independent of the database credentials.
- **One row per record returned or changed.** Each row carries both `referral_id` and `patient_id`, plus old and new provider for assignments. There are no foreign keys, so rows outlive the records they describe.
- **Six audited routes,** with actions `referral.list`, `referral.read`, `patient.create`, `referral.create`, `referral.assign` and `referral.status`. A route-enumeration test fails if a PHI route is added without auditing.
- **Actor from the token** (ADR-0004), never from the request body.
- **Only successful access is recorded.**
- **Fail closed.** The row is written in the route's own transaction. If the insert fails, the request fails and returns nothing.
- **Append-only for `careroute_app`.** The migration and `scripts/db_roles.py` REVOKE UPDATE and DELETE (and TRUNCATE) on `record_access`, so the exception to ADR-0010's read/write grant survives re-running the role bootstrap.
- **Bounded worklist.** The worklist `limit` is capped at 1..100, which bounds rows per request.
- **No automatic pruning.** An operator prunes manually as the migrate role (RUNBOOK → Record access), after exporting any incident window.

## Consequences

- **Accepted: growth.** Every read is a row and nothing prunes them. The manual prune runs as the migrate role through the migrate job.
- **Accepted: timestamp.** `occurred_at` is the transaction start time, not the moment the response was sent.
- **Accepted: ID reuse.** `seed --reset` keeps audit rows but restarts IDs, so an old row may name a different record with the same ID. Every runbook query filters by a time window.
- **Accepted: denied and not-found attempts** appear only in the request log, not in `record_access`.
- **Accepted: IDs, not fields.** Rows record which records were returned, not which fields the client displayed.
- **Accepted: privileged credentials.** A migrate or admin credential can still alter rows. The Log Analytics copy (90 days) is the independent control, so export before it ages out.
- **Accepted: duplicate write lines.** A write request emits both the older `referral.created` / `referral.status_changed` line and the new access line.
