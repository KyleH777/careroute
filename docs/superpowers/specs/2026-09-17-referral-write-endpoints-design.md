# CareRoute — Referral Write Endpoints Design

**Date:** 2026-09-17
**Status:** Approved

## Problem

CareRoute's API is currently read-only: `/health`, `/ready`, `/stats`, and
`/referrals/worklist`. The seeded data (5 facilities, 24 providers, 120
patients, 300 referrals) proves the Docker → Postgres → Alembic → FastAPI
plumbing works end to end, but nothing can actually create or advance a
referral. This design adds the write side of the referral lifecycle the
domain models (`app/models.py`) already describe but nothing exposes.

## Goals

- Create a patient.
- Submit a referral for a patient.
- Assign a provider to a referral, with validation.
- Transition a referral's status through its lifecycle, with validation and
  an audit trail.
- View a single referral including its status-change history.
- No authentication (matches the rest of the API today).
- Automated test coverage for the new business logic, run in isolation from
  the dev database.

## Non-goals

- No endpoints for creating/editing facilities or providers.
- No generic audit log for fields other than `status` — `referral_events`
  stays a status-transition log, as the model already defines it. Assigning
  a provider does not write a `referral_event` row.
- No authentication/authorization.
- No changes to the existing read endpoints.
- No UI.

## API Surface

### `POST /patients`

Request:
```json
{
  "mrn": "string, required, unique",
  "full_name": "string, required",
  "date_of_birth": "YYYY-MM-DD, required",
  "phone": "string, optional",
  "email": "string, optional"
}
```

Response `201`: the created patient (`id, mrn, full_name, date_of_birth,
phone, email, created_at`).

Errors: `409` if `mrn` already exists.

### `POST /referrals`

Request:
```json
{
  "patient_id": "int, required",
  "origin_facility_id": "int, required",
  "specialty_requested": "string, required",
  "priority": "routine | urgent | emergent, optional, default routine",
  "reason": "string, optional",
  "actor": "string, required — who is submitting this"
}
```

Behavior: creates a `Referral` with `status=DRAFT`, `assigned_provider_id=null`,
and writes the first `ReferralEvent` (`from_status=null, to_status=DRAFT,
actor=actor, note=reason`).

Response `201`: the created referral (all columns).

Errors: `404` if `patient_id` or `origin_facility_id` doesn't exist.

### `POST /referrals/{id}/assign`

Request:
```json
{
  "provider_id": "int, required",
  "actor": "string, required",
  "note": "string, optional"
}
```

Behavior: sets `referral.assigned_provider_id = provider_id`. Does **not**
write a `referral_event` (assignment is not a status transition) and does
**not** change `status`.

Validation (all violations return `409` with a message identifying which
rule failed):
- Referral must be in `SUBMITTED` or `ACCEPTED` status.
- Provider's `specialty` must case-insensitively equal the referral's
  `specialty_requested`.
- Provider's `accepting_new_patients` must be `true`.

Errors: `404` if referral or provider doesn't exist.

Response `200`: the updated referral.

### `POST /referrals/{id}/status`

Request:
```json
{
  "to_status": "draft | submitted | accepted | scheduled | completed | cancelled | rejected, required",
  "actor": "string, required",
  "note": "string, optional"
}
```

Behavior: validates the transition against the state machine below. On
success, updates `referral.status` and appends a `ReferralEvent`
(`from_status=<old>, to_status=<new>, actor, note`).

State machine (`app/referral_rules.py`):
```
DRAFT     → SUBMITTED, CANCELLED
SUBMITTED → ACCEPTED, REJECTED, CANCELLED
ACCEPTED  → SCHEDULED, CANCELLED
SCHEDULED → COMPLETED, CANCELLED
COMPLETED → (terminal)
CANCELLED → (terminal)
REJECTED  → (terminal)
```

Errors: `404` if referral doesn't exist. `409` if the transition isn't in
the allowed set above (message states the attempted `from → to`).

Response `200`: the updated referral.

### `GET /referrals/{id}`

Response `200`: the referral plus its `events` (ordered by `occurred_at`):
```json
{
  "id": 1,
  "patient_id": 1,
  "origin_facility_id": 1,
  "assigned_provider_id": null,
  "status": "draft",
  "priority": "routine",
  "specialty_requested": "Cardiology",
  "reason": "...",
  "created_at": "...",
  "updated_at": "...",
  "events": [
    {"from_status": null, "to_status": "draft", "actor": "...", "note": "...", "occurred_at": "..."}
  ]
}
```

Errors: `404` if referral doesn't exist.

## Code structure

- `app/schemas.py` — new. Pydantic request/response models
  (`PatientCreate`, `PatientOut`, `ReferralCreate`, `ReferralOut`,
  `ReferralWithEvents`, `ReferralEventOut`, `ReferralAssignRequest`,
  `ReferralStatusRequest`). All `Out` models use
  `model_config = ConfigDict(from_attributes=True)` to serialize directly
  from ORM instances.
- `app/referral_rules.py` — new. Pure functions, no FastAPI/SQLAlchemy
  session imports:
  - `ALLOWED_TRANSITIONS: dict[ReferralStatus, set[ReferralStatus]]`
  - `validate_transition(current: ReferralStatus, target: ReferralStatus) -> None`
    (raises `ReferralRuleViolation` if illegal)
  - `validate_assignment(referral: Referral, provider: Provider) -> None`
    (raises `ReferralRuleViolation` if illegal)
  - `class ReferralRuleViolation(Exception)`
- `app/main.py` — adds the five routes. Each route stays thin: pull
  objects from the DB, call into `referral_rules` for validation, commit,
  return. Catches `ReferralRuleViolation` once (e.g. via a FastAPI
  exception handler registered on `app`) and converts it to `409`, so
  individual routes don't each need a try/except.

This keeps the existing pattern (`app/main.py`'s docstring: "endpoints are
intentionally thin") while giving the transition/assignment rules a home
that can be understood and unit-tested without spinning up the API layer.

## Testing

New `tests/` directory, pytest + FastAPI's `TestClient` (via `httpx`).
Covers:
- Every entry in `ALLOWED_TRANSITIONS` (valid transitions succeed).
- A representative set of invalid transitions (e.g. `DRAFT → COMPLETED`,
  any transition out of a terminal state) return `409`.
- Assignment validation: specialty mismatch, `accepting_new_patients=false`,
  wrong referral status — each returns `409`.
- Happy path: create patient → create referral → assign provider →
  transition through to `COMPLETED` → `GET` shows full event history.
- 404s for all four ID-taking endpoints against a nonexistent ID.

Why real Postgres, not SQLite: `app/models.py` uses native Postgres enum
types (`referral_status`, `referral_priority`) and a regex `CHECK`
constraint (`npi ~ '^[0-9]{10}$'`) — both Postgres-specific, so SQLite
would silently test different behavior than production.

Why an isolated stack, not the dev database: the dev `db` container holds
the seeded demo data (used for manual verification and the backup/restore
drill); tests must not truncate or mutate it.

### Test infrastructure

New `docker-compose.test.yml` overlay:
```yaml
services:
  db:
    volumes: []   # drop the named volume — ephemeral storage only
  test:
    build:
      context: .
      target: test
    image: careroute:test
    depends_on:
      migrate:
        condition: service_completed_successfully
    environment:
      DATABASE_URL: postgresql+psycopg://careroute:careroute@db:5432/careroute
    command: ["pytest", "-v"]
```

Run under a separate Compose project name so it never touches the dev
stack's containers, network, or volume:
```bash
docker compose -p careroute-test -f docker-compose.yml -f docker-compose.test.yml run --rm test
docker compose -p careroute-test -f docker-compose.yml -f docker-compose.test.yml down -v
```

New `requirements-dev.txt` (`pytest`, `httpx`) — **not** merged into
`requirements.txt`, so the production image doesn't gain extra
dependencies (and extra scanned CVE surface) beyond what's actually needed
to run the app. New Dockerfile stage:
```dockerfile
FROM builder AS test-deps
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt \
    && pip uninstall -y pip

FROM runtime AS test
COPY --from=test-deps --chown=app:app /opt/venv /opt/venv
COPY --chown=app:app tests/ ./tests/
CMD ["pytest", "-v"]
```

## Error handling summary

| Condition | Status |
|---|---|
| Malformed request body (missing field, wrong type, invalid enum value) | `422` (automatic, Pydantic) |
| Referenced patient/facility/provider/referral doesn't exist | `404` |
| Duplicate `mrn` on patient create | `409` |
| Illegal status transition | `409` |
| Assignment rule violated (status/specialty/accepting) | `409` |

## Verification

- `docker compose up --build`, then exercise all five endpoints with
  `curl` against the running dev stack, confirming responses and that
  `GET /referrals/{id}` reflects the actions taken.
- `docker compose -p careroute-test -f docker-compose.yml -f
  docker-compose.test.yml run --rm test` passes, then tear down with
  `down -v`.
- `docker scout quickview careroute:local` still reports 0 critical / 0
  fixable high (the `test` stage is never pushed or run in production, so
  it must not be scanned or shipped).
