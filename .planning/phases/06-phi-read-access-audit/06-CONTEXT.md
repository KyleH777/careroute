# Phase 6: PHI Read-Access Audit - Context
**Gathered:** 2026-09-29 · **Status:** Ready for planning

<domain>
During an incident, the owner can answer "who read or changed which referral/patient record, and when" from the audit trail (AUDIT-01..03). Scope is fixed by ROADMAP.md Phase 6; no new endpoints or features.
</domain>

<decisions>
## Locked (user, 2026-09-29)

**Storage**
- **DB table + audit log line** (Phase 5 pattern). A new Postgres table (working name `record_access`) is the durable record (backed up, PITR). Every audited request also emits `event=audit` JSON via `observability.audit()` so the trail is in Log Analytics (90 days) even if the DB is tampered with.
- **Append-only for the app role:** the API role gets INSERT + SELECT only on the table, no UPDATE/DELETE. A compromised API cannot erase its tracks. Enforced in the DB and covered by a privilege contract test (like `tests/test_db_roles.py`).
- **Provider assignments (AUDIT-02) go in the same table** (action `referral.assign`), with old and new provider IDs in structured columns (old may be NULL). One table answers "everything user Y read or changed".

**Granularity**
- **One DB row per record returned.** A worklist page of 20 → 20 rows. Each row: occurred_at, actor (from the token, ADR-0004, never client-supplied), action, referral_id, patient_id, request_id (Phase 4 contextvar), plus the provider columns for assign.
- **Both referral_id and patient_id on every row**, so "who accessed patient X" needs no join and survives a referral being deleted. `POST /patients` rows have patient_id only.
- **Log Analytics: one line per request**, with ID lists (`referral_ids=[...]`, `patient_ids=[...]`). IDs only, never names/MRNs/DOB/free text. Keeps ingestion low against the 0.5 GB/day cap; KQL uses `mv-expand` for per-record queries.

**What counts as access**
- **Every response containing referral or patient data is audited**, including the write routes that echo the record: `POST /patients`, `POST /referrals`, `POST /referrals/{id}/assign`, `POST /referrals/{id}/status`, plus `GET /referrals/worklist` and `GET /referrals/{id}`. The action names the operation (e.g. `referral.read`, `referral.list`, `patient.create`, `referral.assign`, `referral.status`).
- **Route-enumeration test:** walks `app.routes`. Every route must either audit or appear in a small, named exemption set (e.g. `/health`, `/ready`, `/stats`, `/auth/token`, `/auth/me`, OpenAPI/docs routes). A new route fails CI until someone decides.
- **Only successful access is recorded.** No rows for 403/404/422. Probing is visible in the Phase 4 request log.

**Failure and volume**
- **Fail closed:** access rows are written in the same DB transaction as the request's work, before the response is returned. If the audit write fails, the request fails (5xx) and no PHI leaves.
- **No automatic pruning.** The table keeps everything; the runbook gets a manual "prune older than N days" query run as the **migrate** role (the app role can't DELETE). Revisit if the public demo volume grows.

## Carried forward
- Actor = authenticated user's email from the token (ADR-0004), same as `ReferralEvent.actor` and existing `audit()` calls.
- Audit log lines carry no patient data (Phase 4); Log Analytics retention 90 days, cap 0.5 GB/day (ADR-0012).
- Schema changes via Alembic as the migrate role; deploys through the Phase 3 CI pipeline in ADR-0001 order.
- `.planning/` is public: no secrets, emails, or plan output in planning artifacts.

## Claude's discretion
Table/column/index names, action vocabulary, how the audit hook is attached (dependency, helper, or decorator), how the route test detects "audits", test names, ADR number (next is ADR-0014).
</decisions>

<specifics>
- Success criterion 3 needs queries that **run against the live demo** and return expected rows: "who accessed patient/referral X between T1 and T2" and "everything user Y read or changed", in both SQL (in-VNet job, as in the Phase 5 runbook queries) and KQL.
- Success criterion 4: remove "Reads are not logged" / "Provider assignments are not logged" and the matching rows in the Known-limitations table of `docs/INCIDENT-RESPONSE.md`. Also fix the stale login lines there (login attempts are now logged and rate limited since Phase 5).
- The published `viewer@careroute.demo` account (ADR-0009) means anonymous internet users produce access rows. Expected; covered by the manual prune.
</specifics>

<code_context>
- PHI routes today (`app/main.py`): `GET /referrals/worklist` (returns dicts incl. `patient_id`; no audit), `GET /referrals/{id}` (no audit), `POST /patients` (no audit), `POST /referrals` and `POST /referrals/{id}/status` (ReferralEvent + `audit()`), `POST /referrals/{id}/assign` (**no event, no audit**; old provider is `referral.assigned_provider_id` before overwrite).
- `app/observability.py:audit(action, **fields)` emits `event=audit` JSON; request_id contextvar lives there too.
- `app/login_guard.py` + the `login_attempts` model/migration are the closest analogue (table + record + audit line).
- **Pitfall — grants:** `scripts/db_roles.py` sets `ALTER DEFAULT PRIVILEGES ... GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES` to the app role and also re-runs `GRANT ... ON ALL TABLES`. A new table will automatically get UPDATE/DELETE, and re-running db_roles would re-grant them after a REVOKE in the migration. The append-only rule must survive both (e.g. db_roles excludes/revokes on the audit table, plus a contract test).
- Roles: `READ_ROLES` / `ROUTING_ROLES` in `app/auth.py`.
</code_context>

<canonical_refs>
- `.planning/ROADMAP.md` (Phase 6 success criteria)
- `.planning/REQUIREMENTS.md` (AUDIT-01, AUDIT-02, AUDIT-03)
- `docs/adr/0004-audit-actor-from-token.md`: actor comes from the token
- `docs/adr/0009-read-only-public-demo.md`: public viewer account
- `docs/adr/0010-per-workload-identities-and-db-roles.md`: app vs migrate role privileges
- `docs/adr/0012-alerting-without-availability-probes.md`: Log Analytics retention/cap
- `docs/adr/0013-login-rate-limiting.md`: table + audit-line pattern
- `docs/INCIDENT-RESPONSE.md`: audit-gap text to remove; incident queries go here
- `docs/RUNBOOK.md`: SQL/KQL queries and prune query go here
- `.planning/phases/05-login-hardening/05-CONTEXT.md`: prior pattern
</canonical_refs>

<deferred>
- Scheduled pruning job / formal retention period for access rows (revisit if volume grows).
- Recording denied/not-found access attempts with an outcome column.
</deferred>
