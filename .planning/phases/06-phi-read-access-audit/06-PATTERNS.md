# Phase 6: PHI Read-Access Audit - Pattern Map

**Mapped:** 2026-09-29
**Files analyzed:** 14 (new and modified)
**Analogs found:** 13 / 14

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/models.py` (+`RecordAccess`) | model | CRUD (append-only) | `LoginAttempt` in `app/models.py:276-296` | exact |
| `migrations/versions/2026093x_..._add_record_access.py` | migration | batch (DDL) | `migrations/versions/20260929_1400_add_login_attempts.py` | exact (+ REVOKE step, new) |
| `app/access_audit.py` | service / helper | request-response, write-then-log | `app/login_guard.py` (`record()`) | role-match |
| `app/main.py` (6 PHI routes, worklist `limit`) | route | request-response | itself: `create_referral`, `update_referral_status` (`main.py:253-372`) | exact |
| `scripts/db_roles.py` (REVOKE on append-only tables) | config / provisioning | batch | itself (`bootstrap`, lines 150-177, `REVOKE ALL ON alembic_version`) | exact |
| `tests/test_db_roles.py` (exclusion + append-only contract) | test | contract | itself (lines 31-61) | exact |
| `tests/conftest.py` (`clean_tables`) | test config | batch | itself (`conftest.py:51-59`) | exact |
| `tests/test_access_audit.py` | test | request-response | `tests/test_login_guard.py` + `tests/test_observability.py:68-82` | role-match |
| `tests/test_audit_route_coverage.py` | test | transform (introspection) | none | no analog |
| `docs/adr/0014-phi-access-audit.md` + `docs/adr/README.md` row | docs | n/a | `docs/adr/0013-login-rate-limiting.md` | exact |
| `docs/RUNBOOK.md` (Record access section, gap text) | docs | n/a | RUNBOOK "Login attempts" section (~lines 195-225) | exact |
| `docs/INCIDENT-RESPONSE.md` | docs | n/a | itself (gap bullets ~195-228) | exact |
| `docs/AZURE.md` (retention wording check) | docs | n/a | itself (line ~46) | exact |
| `scripts/seed.py` (no change; decision A3) | script | batch | itself | n/a |

## Pattern Assignments

### `app/models.py` -> `RecordAccess` (model, append-only)

**Analog:** `LoginAttempt`, `app/models.py:276-296`

```python
class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    client_ip: Mapped[str | None] = mapped_column(INET)
    outcome: Mapped[LoginOutcome] = mapped_column(LOGIN_OUTCOME, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_login_attempts_email_time", "email", "occurred_at"),
        Index("ix_login_attempts_ip_time", "client_ip", "occurred_at"),
    )
```

Copy: `occurred_at` server_default `func.now()`, `request_id` String(64) nullable, `Index("ix_<table>_<col>_time", col, "occurred_at")` naming, docstring citing the ADR. Diverge per RESEARCH: `action` as `String(32)` + `CheckConstraint` (not a native enum, so no DROP TYPE wart), no ForeignKeys, `BigInteger` PK, `CheckConstraint("referral_id IS NOT NULL OR patient_id IS NOT NULL")`, indexes `(patient_id, occurred_at)`, `(referral_id, occurred_at)`, `(actor, occurred_at)`.

---

### `migrations/versions/2026093x_..._add_record_access.py` (migration)

**Analog:** `migrations/versions/20260929_1400_add_login_attempts.py`

**Header / revision chain** (lines 1-19):
```python
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '5c1f0e7a9b21'
down_revision: str | None = 'a6ca29d19c0c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
```
New file: `down_revision = '5c1f0e7a9b21'`, new random revision id.

**Create/drop pattern** (lines 22-42):
```python
op.create_table('login_attempts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    ...
    sa.PrimaryKeyConstraint('id'))
op.create_index('ix_login_attempts_email_time', 'login_attempts', ['email', 'occurred_at'], unique=False)
# downgrade: drop_index(...) then drop_table(...)
```
Add after create: guarded REVOKE of UPDATE, DELETE, TRUNCATE from the app role (role name from `os.environ.get("APP_DB_ROLE", "careroute_app")`, same env var and default as `scripts/db_roles.py:182`; skip when `pg_roles` has no such role). No `DROP TYPE` needed since there is no native enum.

---

### `app/access_audit.py` (helper: stage rows in caller's txn, emit log line after commit)

**Analog:** `app/login_guard.py`

**Imports** (lines 10-20):
```python
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import LoginAttempt, LoginOutcome
from app.observability import audit, request_id_var
```

**Record + audit pair** (lines 90-97):
```python
def record(session: Session, email: str, ip: str | None, outcome: LoginOutcome) -> None:
    """Persist the attempt (never the password) and emit an audit line."""
    request_id = request_id_var.get()
    session.add(
        LoginAttempt(email=email, client_ip=ip, outcome=outcome, request_id=request_id)
    )
    session.commit()
    audit("auth.login", email=email, client_ip=ip, outcome=outcome.value)
```
Difference: `login_guard.record` commits itself. `access_audit.stage()` must NOT commit (same transaction as the route's work, fail closed); it uses `session.execute(insert(RecordAccess), rows)` and reads `request_id_var.get()`. `emit()` calls `audit(action, actor=..., referral_ids=[...], patient_ids=[...])` after the route's `commit()`. Docstring convention: module docstring naming the ADR, "IDs only, never names".

`audit()` signature to reuse, `app/observability.py:116-120`:
```python
def audit(action: str, **fields: Any) -> None:
    """Record an audit event (who did what to which record). No free text."""
    audit_log.info(
        action, extra={"fields": {"event": "audit", "action": action, **fields}}
    )
```
Note: `audit(action, actor=...)` collides with no kwarg; existing routes already pass `actor=user.email`.

---

### `app/main.py` (six PHI routes)

**Analog:** the same file. Existing structure to extend (`main.py:253-372`):

Auth/dependency pattern (already used; rename `_user` to `user` where the actor is now needed: worklist, patients, assign, get_referral):
```python
session: Session = Depends(get_session),
user: User = Depends(require_role(*WRITE_ROLES)),
```

Existing commit-then-audit pattern (`main.py:283-301`, create_referral):
```python
session.add(ReferralEvent(referral_id=referral.id, from_status=None,
    to_status=ReferralStatus.DRAFT, actor=user.email, note=payload.reason))
session.commit()
audit("referral.created", actor=user.email, referral_id=referral.id,
      from_status=None, to_status=ReferralStatus.DRAFT.value)
session.refresh(referral)
return referral
```
Insert `stage(session, user.email, "referral.create", pairs)` immediately before `session.commit()`, and `emit(...)` right after it. Keep the existing `audit("referral.created"/"referral.status_changed")` lines (tests/test_observability.py:68-82 assert exactly one `careroute.audit` line for status change: **that test must be updated** since a second line, `referral.status`, will now be emitted; assert on the matching action instead of `len(lines) == 1`).

Assign (`main.py:326-331`) currently:
```python
validate_assignment(referral, provider)
referral.assigned_provider_id = provider.id
session.commit()
session.refresh(referral)
```
Capture `old = referral.assigned_provider_id` before overwriting (RESEARCH "Assign route" example).

Patient create (`main.py:239-250`): existing IntegrityError -> rollback -> 409 pattern. Add `session.flush()` inside the try so a 409 stages nothing, then `stage(...)`, then `commit()`:
```python
session.add(patient)
try:
    session.commit()
except IntegrityError as exc:
    session.rollback()
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=...) from exc
```

Worklist (`main.py:193-229`): `limit: int = 20` becomes `limit: int = Query(20, ge=1, le=100)` (import `Query` from fastapi). `.scalars()` is a lazy result; materialize with `.all()` before staging and before commit. Get_referral (`main.py:375-399`): stage after the 404 check, commit, then build `ReferralWithEvents` (`expire_on_commit=False` per RESEARCH; verify in `app/db.py`).

Decorator order: `@app.get(...)` on top, `@audited("referral.list")` beneath, so the marker is on the function FastAPI registers.

---

### `scripts/db_roles.py` (append-only REVOKE)

**Analog:** itself, `bootstrap()` lines 150-177. Insert after the blanket `GRANT ... ON ALL TABLES` (line 165-170) and next to the existing `REVOKE ALL ON alembic_version` (line 176), still under `SET ROLE migrate`:

```python
cur.execute(
    sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(a)
)
...
cur.execute(sql.SQL("REVOKE ALL ON alembic_version FROM {}").format(a))
cur.execute("RESET ROLE")
```
Add a module constant `APPEND_ONLY_TABLES = ("record_access",)` (importable by the contract test) and, per table, guarded by `cur.execute("select to_regclass(%s)", ("public.record_access",))` (the table does not exist on the first run, since db-roles runs before migrations):
```python
sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON {} FROM {}").format(sql.Identifier(t), a)
```
Use `sql.Identifier` composition exactly as the file does; update the module docstring ("SELECT/INSERT/UPDATE/DELETE only") to mention the append-only exception.

---

### `tests/test_db_roles.py` (contract)

**Analog:** itself.

Existing parametrization to modify (lines 31-36):
```python
@pytest.mark.parametrize("table", [t.name for t in Base.metadata.sorted_tables])
@pytest.mark.parametrize("privilege", ["SELECT", "INSERT", "UPDATE", "DELETE"])
def test_app_has_dml_on_every_model_table(table, privilege):
    assert _scalar("select has_table_privilege(current_user, :t, :p)", t=table, p=privilege)
```
Exclude `APPEND_ONLY_TABLES` from the UPDATE/DELETE combinations (or param-filter the table list). New tests copy `test_app_cannot_write_alembic_version` (lines 56-61, `not _scalar(has_table_privilege...)` per privilege) for UPDATE/DELETE/TRUNCATE on `record_access` plus SELECT/INSERT True, and copy `test_app_cannot_change_schema_or_truncate` (lines 48-53) for real `UPDATE record_access ...` / `DELETE FROM record_access` / `TRUNCATE record_access` raising `psycopg.errors.InsufficientPrivilege`:
```python
with engine.connect() as conn:
    with pytest.raises(ProgrammingError) as exc:
        conn.execute(text(statement))
    conn.rollback()
assert isinstance(exc.value.orig, psycopg.errors.InsufficientPrivilege)
```
Also a test that re-runs `db_roles.bootstrap` (via an admin connection; see `ADMIN_DATABASE_URL` in docker-compose.test.yml) and re-checks the privileges.

---

### `tests/conftest.py`

Add `record_access` to the TRUNCATE list (`conftest.py:51-59`):
```python
"TRUNCATE TABLE referral_events, referrals, patients, "
"providers, facilities, users, login_attempts "
"RESTART IDENTITY CASCADE"
```
Runs via `owner_engine`, so REVOKE does not affect it.

---

### `tests/test_access_audit.py` (test, request-response)

**Analogs:** `tests/test_login_guard.py` (fixtures, DB assertions, owner-engine helper) and `tests/test_observability.py:68-82` (log-line assertions).

Imports/helper pattern (`test_login_guard.py:3-11, 33-45`):
```python
import json
import logging
import pytest
from sqlalchemy import text
from tests.conftest import owner_engine

def _attempts(db):
    db.expire_all()
    return db.query(LoginAttempt).order_by(LoginAttempt.id).all()
```
Audit-line assertion pattern (`test_observability.py:68-82`):
```python
caplog.set_level(logging.INFO, logger="careroute.audit")
response = client.post(f"/referrals/{submitted_referral.id}/status", json={...})
lines = [_json(r) for r in _records(caplog, "careroute.audit")]
assert audit["event"] == "audit"
assert audit["actor"] == "coordinator@test.careroute"
assert audit["request_id"] == response.headers["X-Request-ID"]
assert "free text" not in json.dumps(audit)
```
Use fixtures `client`, `client_as`, `anon_client`, `submitted_referral`, `provider`, `patient`, `facility`, `make_user` (see conftest). For fail-closed, monkeypatch `app.access_audit.stage` (must be referenced as `access_audit.stage` module attribute from `main.py`, or patch where imported) to raise and assert 5xx with no PHI body. The `client` fixture must be created with `raise_server_exceptions=False` for a 500 assertion; check conftest.

---

### `tests/test_audit_route_coverage.py`

No analog. Use RESEARCH "Route-enumeration test": iterate `app.routes` (`fastapi.routing.APIRoute`), check `getattr(route.endpoint, "__audit_action__", None)` or `(method, path)` in a named `EXEMPT` set (`/health`, `/ready`, `/stats`, `/auth/token`, `/auth/me`; docs/openapi routes are not `APIRoute`s), assert `EXEMPT` has no stale entries, plus a behaviour table covering every marked route.

---

### `docs/adr/0014-phi-access-audit.md` and `docs/adr/README.md`

**Analog:** `docs/adr/0013-login-rate-limiting.md`. Structure: `# ADR-0014: <title>`, `- **Status:** Accepted`, `- **Date:** 2026-09-29`, then `## Context`, `## Decision` (bold-lead bullets), `## Consequences` (include "Accepted:" bullets, e.g. growth/no pruning, `now()` is transaction start, seed `--reset` reuses IDs, migrate credential can still alter). README row format:
```
| [0013](0013-login-rate-limiting.md) | Login rate limiting and attempt log in Postgres |
```

### `docs/RUNBOOK.md`

**Analog:** the "Login attempts" section. Copy the `IMG=... READ_ENV=... sql() { ... }` helper block (RUNBOOK ~line 211; do not redefine, refer to it) and the query style:
```bash
sql "select occurred_at, host(client_ip), outcome, request_id from login_attempts where email = 'x@example.com' and outcome <> 'success' and occurred_at > now() - interval '24 hours' order by occurred_at desc"
```
Constraint: SQL is embedded in a double-quoted shell string inside `sa.text("...")`, so no double quotes and no `:word` or `::cast`; use `timestamptz '...'`. Replace the "Know the gaps" paragraph (~lines 302-306) and the closing "Reads are not audited yet" sentence (~555). Prune runs as migrate role, not through `sql()` (which runs as the app role).

### `docs/INCIDENT-RESPONSE.md`

Remove gap bullets (~195-200, ~226, ~228), fix stale login and central-log-store lines, add `record_access` to "What the system records".

## Shared Patterns

### Actor from token (ADR-0004)
**Source:** `app/main.py` routes using `user: User = Depends(require_role(...))`, `actor=user.email` (`main.py:288, 358`).
**Apply to:** all six audited routes. Never add an `actor` field to a schema.

### Audit line, IDs only
**Source:** `app/observability.py:116-120` (`audit()`), `app/login_guard.py:97`.
**Apply to:** `access_audit.emit()`. No names, MRN, DOB, reason, note.

### Commit-then-audit ordering
**Source:** `app/main.py:292-299, 363-370` (`session.commit()` then `audit(...)`, then `session.refresh`).
**Apply to:** every audited route: stage rows -> commit -> emit -> build response.

### Owner-engine vs app-engine in tests
**Source:** `tests/conftest.py` (`owner_engine` for TRUNCATE/updates; `SessionLocal`/`engine` as app role).
**Apply to:** tests that seed or age rows must use the owner engine, since the app role cannot UPDATE/DELETE `record_access`.

### Migration guarding for roles
**Source:** `scripts/db_roles.py:182-183` env var names `APP_DB_ROLE` (default `careroute_app`).
**Apply to:** the migration REVOKE.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `tests/test_audit_route_coverage.py` | test | introspection | No existing test walks `app.routes`; use RESEARCH design |
| REVOKE-in-migration (part of migration) | migration | DDL | No existing migration touches grants; grants live only in `scripts/db_roles.py` |

## Metadata

**Analog search scope:** `app/`, `migrations/versions/`, `scripts/`, `tests/`, `docs/adr/`, `docs/RUNBOOK.md`
**Files scanned:** ~15 read in full or in part
**Pattern extraction date:** 2026-09-29
