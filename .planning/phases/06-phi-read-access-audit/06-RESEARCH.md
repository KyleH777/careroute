# Phase 6: PHI Read-Access Audit - Research

**Researched:** 2026-09-29
**Domain:** FastAPI + SQLAlchemy 2.0 + Postgres 16 audit logging, least-privilege grants, KQL/SQL runbook queries
**Confidence:** HIGH (all findings come from reading the repo; no new packages)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
**Storage**
- DB table + audit log line (Phase 5 pattern). New Postgres table (working name `record_access`) is the durable record (backed up, PITR). Every audited request also emits `event=audit` JSON via `observability.audit()` so the trail is in Log Analytics (90 days) even if the DB is tampered with.
- Append-only for the app role: API role gets INSERT + SELECT only, no UPDATE/DELETE. Enforced in the DB and covered by a privilege contract test (like `tests/test_db_roles.py`).
- Provider assignments (AUDIT-02) go in the same table (action `referral.assign`), old and new provider IDs in structured columns (old may be NULL).

**Granularity**
- One DB row per record returned (worklist page of 20 -> 20 rows). Each row: occurred_at, actor (from token, ADR-0004, never client-supplied), action, referral_id, patient_id, request_id (Phase 4 contextvar), plus provider columns for assign.
- Both referral_id and patient_id on every row (no join for "who accessed patient X"; survives referral deletion). `POST /patients` rows have patient_id only.
- Log Analytics: one line per request with ID lists (`referral_ids=[...]`, `patient_ids=[...]`). IDs only, never names/MRNs/DOB/free text. KQL uses `mv-expand`.

**What counts as access**
- Every response containing referral or patient data is audited, including write routes that echo the record: `POST /patients`, `POST /referrals`, `POST /referrals/{id}/assign`, `POST /referrals/{id}/status`, plus `GET /referrals/worklist` and `GET /referrals/{id}`. Actions e.g. `referral.read`, `referral.list`, `patient.create`, `referral.assign`, `referral.status`.
- Route-enumeration test walks `app.routes`; every route must audit or be in a small named exemption set (`/health`, `/ready`, `/stats`, `/auth/token`, `/auth/me`, OpenAPI/docs routes). A new route fails CI until decided.
- Only successful access is recorded. No rows for 403/404/422.

**Failure and volume**
- Fail closed: access rows written in the same DB transaction as the request's work, before the response is returned. Audit write fails -> request fails (5xx), no PHI leaves.
- No automatic pruning. Runbook gets a manual "prune older than N days" query run as the migrate role.

**Carried forward:** actor = user email from the token; audit lines carry no patient data; Log Analytics 90 days / 0.5 GB/day cap (ADR-0012); Alembic as migrate role, deploy via Phase 3 CI in ADR-0001 order; `.planning/` is public (no secrets/emails).

### Claude's Discretion
Table/column/index names, action vocabulary, how the audit hook is attached (dependency, helper, decorator), how the route test detects "audits", test names, ADR number (next is ADR-0014).

### Deferred Ideas (OUT OF SCOPE)
- Scheduled pruning job / formal retention period for access rows.
- Recording denied/not-found access attempts with an outcome column.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AUDIT-01 | Every read endpoint records who read which referral/patient record, and when | `record_access` table + `app/access_audit.py` helper; stage rows before the route's commit; route-enumeration + behavioural tests |
| AUDIT-02 | Provider assignments recorded | `referral.assign` row with `old_provider_id`/`new_provider_id`, written in the same transaction as the UPDATE |
| AUDIT-03 | Runbook and incident queries use the new logs | SQL (via the `sql()` seed-job helper) and KQL queries; INCIDENT-RESPONSE gap text removal; live verification after deploy |
</phase_requirements>

## Summary

This is a small, well-bounded phase that closely follows Phase 5 (`login_guard` + `login_attempts`). There are exactly six PHI-bearing routes in `app/main.py` (verified by reading the file): `GET /referrals/worklist`, `GET /referrals/{id}`, `POST /patients`, `POST /referrals`, `POST /referrals/{id}/assign`, `POST /referrals/{id}/status`. Exempt: `/health`, `/ready`, `/stats`, `/auth/token`, `/auth/me`, plus FastAPI's `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`. [VERIFIED: app/main.py]

The one non-obvious hard part is **append-only for the app role**. `scripts/db_roles.py` both sets `ALTER DEFAULT PRIVILEGES ... GRANT SELECT, INSERT, UPDATE, DELETE` and re-runs `GRANT ... ON ALL TABLES`. In every environment the order is db-roles -> migrate -> api, so the table is created by the migration *after* default privileges are in force, and the app role silently gets UPDATE/DELETE. A REVOKE therefore has to be done in two places (the migration, and db_roles.py after its blanket GRANT), and `tests/test_db_roles.py::test_app_has_dml_on_every_model_table` (parametrized over every model table for all four privileges) will fail for the new table unless it is adjusted. [VERIFIED: scripts/db_roles.py, tests/test_db_roles.py, docker-compose.test.yml]

Secondary risks: the worklist `limit` parameter is unbounded (`limit: int = 20`), which makes one request able to write an arbitrary number of rows and an oversized log line; `seed.py --reset` and the `clean_tables` fixture need a decision about `record_access`; and success criterion 3 requires running the queries live after deploy, so the plan needs a post-deploy verification task (Log Analytics ingestion lags a few minutes).

**Primary recommendation:** One migration (new table + REVOKE UPDATE, DELETE, TRUNCATE from the app role), one `app/access_audit.py` module (`stage()` inserts rows in the caller's transaction; `emit()` writes the log line after commit), a decorator that marks each route with its action, a route-enumeration test plus a parametrized behavioural test, and a REVOKE mirrored into `db_roles.py`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Identify actor | API / Backend (`get_current_user`, token) | — | ADR-0004: never from request body |
| Record access rows (fail closed) | API / Backend (same SQLAlchemy session/txn as route work) | Database (constraints, grants) | Atomic with the request's work |
| Append-only enforcement | Database (GRANT/REVOKE) | API (no UPDATE/DELETE code path) | A compromised API must not be able to erase rows |
| Central copy of trail | API (`observability.audit()` -> stderr JSON) | Log Analytics (ingest, 90 d) | Survives DB tampering/restore |
| Incident queries | Ops docs (RUNBOOK/INCIDENT-RESPONSE) | Database (SQL), Log Analytics (KQL) | Read-only operator workflow |
| Pruning | Database, as migrate role only | — | App role has no DELETE |

## Standard Stack

No new dependencies. Everything is already pinned in `requirements.txt`: fastapi 0.141.1, sqlalchemy 2.0.36, alembic 1.14.0, psycopg 3.2.3, pytest 8.3.4, ruff, mypy. [VERIFIED: requirements.txt]

### Package Legitimacy Audit
No external packages are installed in this phase. slopcheck not needed. **Packages removed: none. Flagged: none.**

## Architecture Patterns

### Data flow
```
request -> RequestContextMiddleware (request_id_var) -> get_current_user (actor=user.email, same Session)
        -> route work (read/insert/update, flush to get ids)
        -> access_audit.stage(session, actor, action, rows)   # INSERT into record_access, same txn, no commit
        -> session.commit()                                     # any failure here -> 5xx, no response body
        -> access_audit.emit(...)                               # one audit() line with ID lists, after commit
        -> response serialized and returned
```
Failure paths (401/403/404/409/422 raised before staging) write nothing.

### Recommended structure
```
app/models.py                      # + RecordAccess model
app/access_audit.py                # stage(), emit(), @audited(action) marker, ACTIONS
migrations/versions/2026093x_..._add_record_access.py   # down_revision = '5c1f0e7a9b21'
scripts/db_roles.py                # + REVOKE UPDATE, DELETE, TRUNCATE on record_access from app
tests/test_access_audit.py         # behaviour, fail-closed, no-PHI-in-log, actor-spoof
tests/test_audit_route_coverage.py # route enumeration
tests/test_db_roles.py             # exclude record_access from DML param test; add append-only contract
docs/adr/0014-phi-access-audit.md ; docs/adr/README.md row
```

### Table design (recommendation)
`record_access`: `id` BigInteger PK identity; `occurred_at` timestamptz `server_default now()` NOT NULL; `actor` String(255) NOT NULL; `action` **String(32) + CheckConstraint** (not a native enum: adding an action later then needs no `ALTER TYPE`, and it avoids the `DROP TYPE` downgrade wart seen in the `login_attempts` migration); `referral_id` Integer NULL; `patient_id` Integer NULL; `old_provider_id`, `new_provider_id` Integer NULL; `request_id` String(64) NULL. **No foreign keys** (rows must survive deletion of the referenced record; FKs would also block deletes or cascade the audit away). Indexes: `(patient_id, occurred_at)`, `(referral_id, occurred_at)`, `(actor, occurred_at)`. Add a CheckConstraint that `referral_id IS NOT NULL OR patient_id IS NOT NULL`. [ASSUMED: column sizing/naming, discretion area]

Note `now()` in Postgres is the *transaction start* time. The transaction begins at the auth query in `get_current_user`, so `occurred_at` is milliseconds before the response. Fine for incident work; mention in the ADR. [VERIFIED: Postgres semantics, docs]

### Pattern 1: helper + marker decorator
```python
# app/access_audit.py (sketch)
def audited(action: str):
    def mark(fn):
        fn.__audit_action__ = action   # read by the route-coverage test
        return fn
    return mark

def stage(session, actor: str, action: str, pairs, *, old_provider_id=None, new_provider_id=None):
    """INSERT one row per (referral_id, patient_id) pair. No commit: caller's txn."""
    rows = [dict(actor=actor, action=action, referral_id=r, patient_id=p,
                 old_provider_id=old_provider_id, new_provider_id=new_provider_id,
                 request_id=request_id_var.get()) for r, p in pairs]
    if rows:
        session.execute(insert(RecordAccess), rows)   # one executemany/insertmanyvalues batch
    return rows

def emit(actor, action, pairs, **extra):
    audit(action, actor=actor,
          referral_ids=sorted({r for r, _ in pairs if r is not None}),
          patient_ids=sorted({p for _, p in pairs if p is not None}), **extra)
```
Decorator order: `@app.get(...)` on top, `@audited("referral.list")` beneath it, so the marker is on the function FastAPI registers. Route test reads `route.endpoint.__audit_action__`. [ASSUMED: design; consistent with CONTEXT discretion]

### Per-route wiring
| Route | Action | Rows (referral_id, patient_id) | Where to stage |
|---|---|---|---|
| GET /referrals/worklist | `referral.list` | each returned referral | after query, then `session.commit()` before building the response |
| GET /referrals/{id} | `referral.read` | the referral | after 404 check, commit, then build `ReferralWithEvents` (`expire_on_commit=False`, so objects stay usable) |
| POST /patients | `patient.create` | `(None, patient.id)` | `session.add`, `session.flush()` **inside** the IntegrityError try (409 path writes nothing), then stage, then commit |
| POST /referrals | `referral.create` | the referral | after the existing `flush()` + ReferralEvent add, stage **before** the existing `session.commit()` |
| POST /referrals/{id}/assign | `referral.assign` | the referral + old/new provider | capture `old = referral.assigned_provider_id` **before** overwriting; stage before the single commit |
| POST /referrals/{id}/status | `referral.status` | the referral | stage before the existing commit |

Keep the existing `audit("referral.created"...)` and `audit("referral.status_changed"...)` lines unchanged (existing RUNBOOK KQL and `tests/test_observability.py` depend on them); the new lines use distinct action names, so there is no collision, but a write request yields two audit lines. The "everything user Y read or changed" KQL should key on the new actions (or accept both) rather than counting lines. Emit the new line after `commit()` so a failed commit never produces a line for something that did not persist. [VERIFIED: tests/test_observability.py:68-82]

### Route-enumeration test
Walk `app.routes`, take `APIRoute`s (skip `Mount`/plain `Route` docs handled via the exempt set on `(method, path)`). Assert: for each, either `getattr(route.endpoint, "__audit_action__", None)` is set, or `(method, path)` is in `EXEMPT`. Also assert `EXEMPT` has no stale entries (each exempt path still exists) and each audited route's action is in the `ACTIONS` set. A marker alone proves declaration, not behaviour, so add a **parametrized behavioural test**: one table mapping each audited route to a request builder using existing fixtures (`client`, `submitted_referral`, `provider`, `patient`), asserting >=1 `record_access` row with the declared action and a matching audit log line. A new route with a marker but no behaviour-table entry fails a "table covers every marked route" assertion. [ASSUMED: design]

### Anti-patterns
- **Middleware-based auditing:** middleware cannot see returned IDs without parsing response bodies, and runs after the transaction; do not use it.
- **`Depends` with yield teardown for the write:** teardown timing relative to the response has changed across FastAPI versions; explicit call inside the handler is deterministic and fail-closed.
- **Client-supplied actor:** never add an `actor` field to any schema; actor is `user.email` from `require_role(...)`. Rename `_user` to `user` in routes that now use it.
- **Logging PII in the audit line:** no MRN/name/DOB/reason/note; IDs and enum-like strings only. Do not log `payload` objects.
- **Separate transaction/autonomous audit write:** defeats fail-closed; must share the route's session.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Append-only | App-level "don't call update" convention, or triggers | Postgres `REVOKE UPDATE, DELETE, TRUNCATE` from app role; table owned by migrate | Enforced by the DB even if the API is compromised |
| Bulk insert | Row-by-row loop | `session.execute(insert(RecordAccess), list_of_dicts)` | One round-trip (insertmanyvalues) |
| Log shipping | Custom shipper | Existing `audit()` -> stderr JSON -> Container Apps -> Log Analytics | Already live (Phase 4) |
| Request IDs | New context var | `observability.request_id_var` | Already stamped on log lines |

## Common Pitfalls

### Pitfall 1: Default privileges re-grant UPDATE/DELETE
**What goes wrong:** Migration REVOKEs, but the next `db_roles.py` run (every compose up, CI, password rotation, post-restore) re-issues `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES` and the app can rewrite the audit table. Also, on a first deploy the migration runs after default privileges exist, so without an explicit REVOKE the grant is there from the start.
**How to avoid:** (a) In the migration: `REVOKE UPDATE, DELETE, TRUNCATE ON record_access FROM <app role>` guarded by a role-exists check (`DO $$ ... IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = ...) ...`), role name from `os.environ.get("APP_DB_ROLE", "careroute_app")` to match db_roles.py, so environments without the roles (plain dev DB) do not break. (b) In `db_roles.py`, after the blanket GRANT and before `RESET ROLE`: `REVOKE UPDATE, DELETE, TRUNCATE ON record_access FROM app` guarded by `to_regclass('public.record_access') IS NOT NULL` (db-roles runs before the first migration when the table does not exist yet). Keep both; they are idempotent. (c) Contract test: `has_table_privilege(current_user, 'record_access', 'UPDATE'|'DELETE'|'TRUNCATE')` is False, INSERT/SELECT True, and a real `UPDATE`/`DELETE` as the app engine raises `InsufficientPrivilege`, mirroring `test_app_cannot_change_schema_or_truncate`. Use a generic list (`APPEND_ONLY_TABLES = ["record_access"]`) so the next audit table is one line. [VERIFIED: scripts/db_roles.py, test structure]
**Warning signs:** `test_app_has_dml_on_every_model_table[record_access-UPDATE]` failing in CI is expected until that test excludes append-only tables.

### Pitfall 2: Existing tests and tooling that touch every table
- `tests/conftest.py::clean_tables` TRUNCATE list (owner engine) must add `record_access`, or rows leak between tests. It runs as the owner so the REVOKE does not matter.
- `test_db_roles.py::test_app_has_dml_on_every_model_table` needs the append-only exclusion (above).
- `scripts/seed.py::reset` truncates seeded tables with `RESTART IDENTITY`, which **reuses referral/patient IDs**. Recommendation: do not truncate `record_access` from seed (audit is not seed data, and `--reset` is a dev/demo tool), and note in the ADR/runbook that a `--reset` invalidates ID meaning for older rows. [ASSUMED: needs owner confirmation, see Open Questions]
- `/stats` `_COUNTED` need not include the new table.

### Pitfall 3: Unbounded worklist `limit`
`limit: int = 20` accepts any integer (negative gives Postgres LIMIT error -> 500; huge gives a huge insert and a huge log line; Container Apps/containerd splits console lines around 16 KB). Bound it: `limit: int = Query(20, ge=1, le=100)`. 100 IDs is ~1 KB of log. This is a small behaviour change (422 beyond 100); no existing test uses it (grep of tests). [VERIFIED: app/main.py, tests grep] [ASSUMED: 100 as the cap]

### Pitfall 4: Read routes now write, so they need a commit and can conflict
GET handlers previously never committed. A read that stages rows must commit before returning. Also a DB outage/`permission denied` now turns reads into 500s (intended: fail closed), and `/ready` is unaffected. Confirm read-only public demo viewer (ADR-0009) still works: the app role keeps INSERT on `record_access`, and the sequence USAGE default grant covers the identity sequence. [VERIFIED: db_roles.py grants sequences via default privileges]

### Pitfall 5: `sql()` runbook helper quoting
The helper embeds `$1` inside `sa.text(\"$1\")` in a double-quoted shell string: SQL must not contain double quotes, and `:name` sequences are bind params in `sa.text`. Timestamps like `'2026-09-29 10:00:00'` are safe (colon preceded by a word char), but avoid `::cast` syntax and any `:word`; use `timestamptz '...'` or `cast('...' as timestamptz)`. Every query must be **run live** for criterion 3, so treat any quoting failure as a task-level defect. [VERIFIED: docs/RUNBOOK.md:211]

### Pitfall 6: Log Analytics lag and dynamic arrays
Ingestion takes a few minutes, so the live KQL check must wait/retry. `referral_ids` is a JSON array inside `Log_s`; after `parse_json`, use `array_index_of(e.patient_ids, 42) >= 0` for "patient X" and `mv-expand` only for per-record listings. Cast with `toint()`. Retention: ADR-0012 and CONTEXT say 90 days, but `docs/AZURE.md` line 46 says "30-day retention"; check `infra/monitoring.tf` and fix whichever is stale while editing docs. [VERIFIED: AZURE.md; monitoring.tf not read]

### Pitfall 7: Duplicated/empty audit lines
Worklist returning zero rows: no DB rows; still emit the line with empty lists (cheap; shows the call happened). De-duplicate IDs in lists (a worklist can repeat a patient). Provider IDs are not PHI but stay as structured fields, not free text.

## Code Examples

### Migration REVOKE (guarded)
```python
def upgrade() -> None:
    op.create_table('record_access', ...)          # autogenerate, then hand-edit
    op.create_index(...)
    op.execute("""
      DO $$
      DECLARE app_role text := coalesce(current_setting('careroute.app_role', true), 'careroute_app');
      BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = app_role) THEN
          EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON record_access FROM %I', app_role);
        END IF;
      END $$;""")
```
(Simpler and preferred: read `os.environ.get("APP_DB_ROLE", "careroute_app")` in Python and interpolate via `sa.text` with a validated identifier / `psycopg.sql`-style quoting; do not string-format untrusted input. The env var is operator-controlled, not user input.) [ASSUMED: exact form]

### Assign route
```python
old = referral.assigned_provider_id
referral.assigned_provider_id = provider.id
pairs = [(referral.id, referral.patient_id)]
stage(session, user.email, "referral.assign", pairs, old_provider_id=old, new_provider_id=provider.id)
session.commit()
emit(user.email, "referral.assign", pairs, old_provider_id=old, new_provider_id=provider.id)
session.refresh(referral)
```

### Runbook SQL (to be run live)
```sql
-- who accessed patient 42 (any route) between T1 and T2
select occurred_at, actor, action, referral_id, request_id from record_access
where patient_id = 42 and occurred_at between timestamptz '2026-09-29 00:00+00' and timestamptz '2026-09-30 00:00+00'
order by occurred_at;
-- everything user Y read or changed
select occurred_at, action, referral_id, patient_id, old_provider_id, new_provider_id from record_access
where actor = 'y@example.com' order by occurred_at desc limit 200;
```
```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated between (datetime(<T1>) .. datetime(<T2>))
| extend e = parse_json(Log_s)
| where tostring(e.event) == "audit" and array_index_of(e.patient_ids, <id>) >= 0
| project TimeGenerated, actor = tostring(e.actor), action = tostring(e.action), request_id = tostring(e.request_id)
```
Prune (manual, migrate role, via `MIGRATE_ENV` job or local superuser psql): `delete from record_access where occurred_at < now() - interval '90 days'`. [VERIFIED: role/job table in AZURE.md "Querying the database from inside the VNet"]

## Docs to edit (criterion 4 and 3)
- `docs/INCIDENT-RESPONSE.md`: remove "Reads are not logged" and "Provider assignments are not logged" bullets (~lines 195-198); fix the stale login bullet (~199-200: says no login access log and no rate limiting, both false since Phase 5) and the "no central log store" bullet (Phase 4); delete Known-limitations rows "No read/access logging" and "Assignment not in the audit log" (~226, 228); add `record_access` queries and a mention in "What the system records".
- `docs/RUNBOOK.md`: "See what an account did" gap paragraph (~302-306) and the closing "Reads are not audited yet" sentence (~555); add a "Record access" section (SQL + KQL + prune); update the Database roles table/notes to mention append-only.
- `docs/adr/0014-phi-access-audit.md` + `docs/adr/README.md` row; ADR-0004's consequences mention the gaps (leave, add "closed by ADR-0014" only if repo convention allows editing ADRs).
- `docs/AZURE.md`: retention wording check (Pitfall 6); `docs/adr/0010` note on append-only exception if desired.

## State of the Art
Not applicable beyond: prefer DB grants over triggers for append-only. A trigger that raises on UPDATE/DELETE would also block the legitimate prune by the owner, so grants are the right control. [ASSUMED]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | `action` as String(32)+CHECK rather than native enum; no FKs; index set | Table design | Low; schema tweak |
| A2 | Cap worklist `limit` at 100 (ge=1) | Pitfall 3 | Low; small API behaviour change, confirm with owner |
| A3 | Do not truncate `record_access` in `seed.py --reset` | Pitfall 2 | Medium: ID reuse makes old rows ambiguous; owner may prefer truncating in dev only |
| A4 | Decorator marker + behavioural table is the coverage design | Route-enumeration test | Low |
| A5 | Emit the log line after commit; keep existing `referral.created`/`status_changed` lines | Per-route wiring | Low |

## Open Questions

1. **seed --reset and audit rows (A3).** Recommendation: leave `record_access` alone, document. Planner may surface to the owner.
2. **Worklist limit cap (A2).** Recommendation: cap at 100.
3. **AZURE.md 30-day vs 90-day retention.** Check `infra/monitoring.tf`; doc fix only.
4. **Empty worklist line.** Recommendation: emit a line with empty lists.

## Environment Availability

| Dependency | Required By | Available | Notes |
|---|---|---|---|
| Docker / compose | test stack (`docker-compose.test.yml`), local run | yes (Docker 29.8.1) | Test stack is the only supported way to run the suite (needs Postgres roles) |
| Python 3 / pytest on host | — | yes but not usable alone | Tests need the compose Postgres; run via compose |
| Azure CLI + live demo access | criterion 3 live verification | not probed | Requires post-deploy human/CLI step; CI deploys on push to main |

## Validation Architecture

### Test Framework
| Property | Value |
|---|---|
| Framework | pytest 8.3.4 + httpx TestClient, ephemeral Postgres 16 with role split |
| Config | `pyproject.toml` (`testpaths = ["tests"]`); fixtures in `tests/conftest.py` |
| Quick run | `docker compose -p careroute-test -f docker-compose.test.yml run --rm test pytest -x -q tests/test_access_audit.py tests/test_audit_route_coverage.py tests/test_db_roles.py` |
| Full suite | `docker compose -p careroute-test -f docker-compose.test.yml run --rm test` then `... down -v`; plus `ruff check . && ruff format --check . && mypy app` |

### Phase Requirements -> Test Map
| Req | Behavior | Type | Command | Exists? |
|---|---|---|---|---|
| AUDIT-01 | Each of the 6 PHI routes writes rows with token actor, ids, request_id | integration | `pytest tests/test_access_audit.py` | Wave 0 |
| AUDIT-01 | Worklist of N -> N rows, N ids in one log line | integration | same | Wave 0 |
| AUDIT-01 | Every non-exempt route audited (enumeration) | unit | `pytest tests/test_audit_route_coverage.py` | Wave 0 |
| AUDIT-01 | 403/404/422/409 write no rows; viewer role read is recorded | integration | same | Wave 0 |
| AUDIT-01 | Fail closed: monkeypatch `stage` (or revoke INSERT as owner) -> 5xx and no PHI body | integration | same | Wave 0 |
| AUDIT-01 | Actor spoof: body/query/header `actor` ignored (ADR-0004) | integration | same | Wave 0 |
| AUDIT-01 | Log line has no name/MRN/DOB/reason (caplog scan over a request with known sentinel PHI strings) | integration | same | Wave 0 |
| AUDIT-02 | assign writes old(NULL then id)/new provider; reassign records prior; failed validation writes none | integration | `pytest tests/test_access_audit.py -k assign` | Wave 0 |
| Append-only | app role lacks UPDATE/DELETE/TRUNCATE on record_access, real statements raise; survives a re-run of `db_roles.bootstrap` | contract | `pytest tests/test_db_roles.py` | update existing |
| Migration | upgrade/downgrade round-trip (CI already does) | CI | CI job | exists |
| AUDIT-03 | Runbook SQL runs against the test DB and returns expected rows (parse the fenced queries or duplicate them in a test with sample data) | integration | `pytest tests/test_access_audit.py -k runbook` | Wave 0 |
| AUDIT-03 | Queries run against live demo | manual (post-deploy) | RUNBOOK `sql` helper + `az monitor log-analytics query` | manual; record evidence in VERIFICATION |
| Docs | INCIDENT-RESPONSE no longer contains "Reads are not logged" / "Assignment not in the audit log" | unit (grep test) | `pytest -k docs_gaps` or a shell grep in verification | Wave 0 (optional) |

### Sampling Rate
- Per task commit: quick run above. Per wave: full suite + ruff + mypy. Phase gate: full suite green, then live verification after the CI deploy.

### Wave 0 Gaps
- [ ] `tests/test_access_audit.py`, `tests/test_audit_route_coverage.py`
- [ ] `conftest.py`: add `record_access` to `clean_tables`; helper fixture to read rows via owner engine or app SELECT
- [ ] `test_db_roles.py`: exclude append-only tables from the DML-on-every-table test

## Security Domain (ASVS L1, block on high)

| ASVS Category | Applies | Control |
|---|---|---|
| V2 Authentication | no change | existing JWT + argon2 |
| V3 Session Management | no change | — |
| V4 Access Control | yes | `require_role` unchanged; `record_access` is INSERT/SELECT only for app; owner-only DELETE |
| V5 Input Validation | yes | bound worklist `limit`; no client-supplied actor; parameterized inserts (SQLAlchemy Core), no string-built SQL |
| V7 Logging & Error Handling | yes (primary) | no PHI in log lines; fail closed; audit integrity |
| V6 Cryptography | no | — |

| Threat | STRIDE | Mitigation |
|---|---|---|
| Actor spoofing | Spoofing | Actor only from `user.email` of the verified token; test asserts ignoring of client `actor` |
| Compromised API erases its tracks | Tampering/Repudiation | REVOKE UPDATE/DELETE/TRUNCATE; second copy in Log Analytics; contract test; REVOKE in both migration and db_roles |
| PHI leaking into logs | Information disclosure | IDs and action names only; test with sentinel PHI; never log payloads or exception text containing row data |
| Audit write failure lets PHI out | Repudiation | same-transaction insert before response; 5xx on failure; test |
| Log/table flooding by public viewer account (ADR-0009) or huge `limit` | DoS | `limit` cap; login rate limiting (Phase 5); manual prune; 0.5 GB/day cap noted |
| Audit-table read exposure | Info disclosure | Table holds IDs + emails only; no API route exposes it; only DB roles read it |
| Oversized/forged request IDs polluting rows | Tampering | `request_id_var` already validated by regex `^[A-Za-z0-9._-]{8,64}$` or replaced by uuid |
| SQL injection in runbook queries | Tampering | Operator-run only; use literals from incident notes carefully; not exposed via the API |

Residual (document in ADR): a compromised migrate/admin credential can still alter the table; the Log Analytics copy is the independent control. Access rows record the returning of IDs, not which fields were shown.

## Sources
- Repo files read: `app/main.py`, `app/observability.py`, `app/login_guard.py`, `app/auth.py`, `app/models.py`, `app/db.py`, `scripts/db_roles.py`, `scripts/seed.py`, `tests/conftest.py`, `tests/test_db_roles.py`, `tests/test_login_guard.py`, `tests/test_observability.py`, `migrations/versions/20260929_1400_add_login_attempts.py`, `migrations/env.py`, `docker-compose.test.yml`, `docs/RUNBOOK.md`, `docs/INCIDENT-RESPONSE.md`, `docs/AZURE.md`, ADRs 0004, 0010, 0013, Phase 5 research/verification (all HIGH).
- Not verified this session: FastAPI/Postgres upstream docs (no version-sensitive API is relied on beyond SQLAlchemy 2.0 `insert()` with a list of dicts, standard); `infra/monitoring.tf` retention.

## Metadata
**Confidence:** stack HIGH (no new deps), architecture HIGH (mirrors Phase 5), pitfalls HIGH (grants issue confirmed in source).
**Research date:** 2026-09-29. **Valid until:** ~30 days.
