# CareRoute Referral Write Endpoints — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the write side of the referral lifecycle to CareRoute's API — create a patient, submit a referral, assign a provider, transition status, and view a referral's full history — with validated business rules and no auth, per `docs/superpowers/specs/2026-09-17-referral-write-endpoints-design.md`.

**Architecture:** Two new pure-Python modules (`app/schemas.py` for request/response shapes, `app/referral_rules.py` for the transition state machine and assignment validation) plumbed into five new thin routes in `app/main.py`. A new isolated pytest harness (separate Dockerfile stage + `docker-compose.test.yml` file + its own Postgres, run under a distinct Compose project name) verifies all of it without touching the dev database or bloating the production image.

**Tech Stack:** FastAPI 0.141.1, SQLAlchemy 2.0, Pydantic v2, pytest 8.3, httpx (via FastAPI's `TestClient`), Postgres 16, Docker Compose.

---

## Task 1: Test infrastructure

**Files:**
- Modify: `docker-compose.yml`
- Create: `requirements-dev.txt`
- Modify: `Dockerfile`
- Create: `docker-compose.test.yml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

This task sets up the whole test harness before any feature code exists, and proves it works end to end against a throwaway Postgres. Every later task just adds tests to this harness.

- [ ] **Step 1: Pin the production build target**

Adding new Dockerfile stages after `runtime` would silently change what a bare `docker build .` produces (Docker defaults to the *last* stage in the file). Pin `migrate` and `api` to `target: runtime` explicitly so they can never accidentally build the test stage.

Modify `docker-compose.yml`. Change:
```yaml
  migrate:
    build:
      context: .
    image: careroute:local
```
to:
```yaml
  migrate:
    build:
      context: .
      target: runtime
    image: careroute:local
```
And change:
```yaml
  api:
    build:
      context: .
    image: careroute:local
```
to:
```yaml
  api:
    build:
      context: .
      target: runtime
    image: careroute:local
```

- [ ] **Step 2: Add test-only dependencies**

Create `requirements-dev.txt`:
```
pytest==8.3.4
httpx==0.28.1
```

This stays separate from `requirements.txt` on purpose — the production image must not gain extra dependencies (and extra CVE-scanned surface) it doesn't need at runtime.

- [ ] **Step 3: Add the Dockerfile test stages**

Modify `Dockerfile`. The `builder` stage currently ends with:
```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y pip
```
Leave that as-is. After the full `runtime` stage (i.e., at the end of the file, after the existing `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` line), append:

```dockerfile

# ============================================================
# Stage 3: test-deps — builder's venv plus dev/test-only
# dependencies (pytest, httpx). Never published.
# ============================================================
FROM builder AS test-deps

# builder already uninstalled pip from its venv (see Stage 1); bring it
# back just long enough to install the dev dependencies below. ensurepip
# only creates versioned pip3/pip3.12 scripts here (no plain `pip`), so a
# bare `pip install` would silently fall through PATH to the base image's
# system pip and install outside the venv — `python -m pip` is unambiguous.
RUN python -m ensurepip --upgrade

COPY requirements-dev.txt .
RUN python -m pip install --no-cache-dir -r requirements-dev.txt

# ============================================================
# Stage 4: test — the runtime image plus test-deps' venv (adds
# pytest/httpx) and the tests/ directory. Used only by the
# `test` service in docker-compose.test.yml; never pushed.
# ============================================================
FROM runtime AS test

COPY --from=test-deps --chown=app:app /opt/venv /opt/venv
COPY --chown=app:app tests/ ./tests/

CMD ["pytest", "-v"]
```

- [ ] **Step 4: Add the test compose file**

Create `docker-compose.test.yml`. Deliberately **standalone** — not merged
with `docker-compose.yml` via `-f`. An override-based version was tried
first (`db: {ports: [], volumes: [], container_name: ...}` layered on top
of `docker-compose.yml`), but on this Compose version, overriding a list
field with `[]` or a scalar with `null` doesn't clear the base value — it's
silently ignored — so the override attempt still collided with the dev
stack's running `careroute-db` container and its published port 5432.
Defining `db`/`migrate`/`test` standalone here sidesteps that entirely:
```yaml
# Isolated test stack: ephemeral Postgres + a one-shot pytest run.
#
#   docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
#   docker compose -p careroute-test -f docker-compose.test.yml down -v
#
# Always run with -p careroute-test: a distinct Compose project name keeps
# this stack's containers and network entirely separate from the dev stack
# (which has real seeded data you don't want tests anywhere near). Always
# pass --build: `run` does not rebuild an already-tagged image on its own,
# so a stale careroute:test image would otherwise be reused silently.

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: careroute
      POSTGRES_PASSWORD: careroute
      POSTGRES_DB: careroute
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U careroute -d careroute"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 5s
    # No published port, no named volume: reached only over this stack's
    # internal network, and data must not survive between runs.

  migrate:
    build:
      context: .
      target: runtime
    image: careroute:local
    environment:
      DATABASE_URL: postgresql+psycopg://careroute:careroute@db:5432/careroute
    depends_on:
      db:
        condition: service_healthy
    command: ["alembic", "upgrade", "head"]
    restart: "no"

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

- [ ] **Step 4a: Allow `tests/` into the Docker build context**

`.dockerignore` excludes `tests/` (it was written before this feature
existed, to keep test code out of the build context entirely). The new
`test` Dockerfile stage needs to `COPY tests/`, so remove that line. This
is safe for the production image: only the `test` stage copies `tests/` —
`runtime` never does — so `careroute:local` is unaffected either way.

Modify `.dockerignore`. Remove the `tests/` line:
```
*.md
docs/
.pytest_cache/
```
(previously `tests/` sat between `docs/` and `.pytest_cache/` — delete
that line only, leave the rest as-is).

- [ ] **Step 5: Add the shared test fixtures**

Create `tests/__init__.py` (empty file — makes `tests/` an importable package):
```python
```

Create `tests/conftest.py`:
```python
"""Shared pytest fixtures.

Runs against the ephemeral Postgres started by docker-compose.test.yml.
`clean_tables` is autouse so every test starts with empty tables — no test
depends on another test's data, and none of this touches the dev stack's
seeded database (a separate container entirely).
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal, engine
from app.main import app
from app.models import (
    Facility,
    Patient,
    Provider,
    Referral,
    ReferralPriority,
    ReferralStatus,
)


@pytest.fixture(autouse=True)
def clean_tables():
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE referral_events, referrals, patients, "
                "providers, facilities RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture()
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def facility(db):
    f = Facility(name="Test Clinic", city="Testville", state="CA")
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


@pytest.fixture()
def provider(db, facility):
    p = Provider(
        facility_id=facility.id,
        npi="1234567890",
        full_name="Dr. Test",
        specialty="Cardiology",
        accepting_new_patients=True,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture()
def patient(db):
    p = Patient(
        mrn="MRN-FIXTURE-001",
        full_name="Fixture Patient",
        date_of_birth=date(1990, 1, 1),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture()
def submitted_referral(db, facility, patient):
    referral = Referral(
        patient_id=patient.id,
        origin_facility_id=facility.id,
        specialty_requested="Cardiology",
        priority=ReferralPriority.ROUTINE,
        status=ReferralStatus.SUBMITTED,
    )
    db.add(referral)
    db.commit()
    db.refresh(referral)
    return referral
```

Create `tests/test_smoke.py`:
```python
"""Smoke test: proves the pytest harness (Docker test stage + ephemeral
Postgres + migrations) actually works, before any feature code is added."""


def test_health_endpoint_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 6: Run the test stack and verify it passes**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: build succeeds, `db` becomes healthy, `migrate` exits 0, then pytest runs and reports `1 passed`.

Then tear down:
```bash
docker compose -p careroute-test -f docker-compose.test.yml down -v
```

- [ ] **Step 7: Verify the production build wasn't affected**

Run:
```bash
cd "/Users/kyleharrington/Desktop/AI/Docker/CareRoute"
docker compose build
docker scout quickview careroute:local
```
Expected: build succeeds, and the scout summary still shows `0C` critical and the "No fixable critical or high vulnerabilities" policy still passes (unchanged from before this task — `careroute:local` must be built from `target: runtime`, not `test`).

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml docker-compose.test.yml requirements-dev.txt Dockerfile .dockerignore tests/
git commit -m "test(careroute): add isolated pytest harness for write endpoints

New docker-compose.test.yml file runs pytest against an ephemeral,
unpublished Postgres under its own Compose project name, so tests
never touch the dev stack's seeded database. Test-only deps
(pytest, httpx) live in requirements-dev.txt and a new Dockerfile
test stage, kept out of the production image. migrate/api are now
pinned to target: runtime so the new stages can never be built by
accident."
```

---

## Task 2: Referral lifecycle rules

**Files:**
- Create: `app/referral_rules.py`
- Create: `tests/test_referral_rules.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_referral_rules.py`:
```python
"""Unit tests for the referral lifecycle rules — pure functions, no HTTP
layer, no database writes required."""

import pytest

from app.models import Provider, Referral, ReferralPriority, ReferralStatus
from app.referral_rules import (
    ALLOWED_TRANSITIONS,
    ReferralRuleViolation,
    validate_assignment,
    validate_transition,
)


@pytest.mark.parametrize(
    "current,target",
    [
        (ReferralStatus.DRAFT, ReferralStatus.SUBMITTED),
        (ReferralStatus.DRAFT, ReferralStatus.CANCELLED),
        (ReferralStatus.SUBMITTED, ReferralStatus.ACCEPTED),
        (ReferralStatus.SUBMITTED, ReferralStatus.REJECTED),
        (ReferralStatus.SUBMITTED, ReferralStatus.CANCELLED),
        (ReferralStatus.ACCEPTED, ReferralStatus.SCHEDULED),
        (ReferralStatus.ACCEPTED, ReferralStatus.CANCELLED),
        (ReferralStatus.SCHEDULED, ReferralStatus.COMPLETED),
        (ReferralStatus.SCHEDULED, ReferralStatus.CANCELLED),
    ],
)
def test_valid_transitions_do_not_raise(current, target):
    validate_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [
        (ReferralStatus.DRAFT, ReferralStatus.COMPLETED),
        (ReferralStatus.DRAFT, ReferralStatus.ACCEPTED),
        (ReferralStatus.SUBMITTED, ReferralStatus.SCHEDULED),
        (ReferralStatus.COMPLETED, ReferralStatus.SUBMITTED),
        (ReferralStatus.CANCELLED, ReferralStatus.DRAFT),
        (ReferralStatus.REJECTED, ReferralStatus.SUBMITTED),
    ],
)
def test_invalid_transitions_raise(current, target):
    with pytest.raises(ReferralRuleViolation):
        validate_transition(current, target)


def test_every_status_has_a_transition_entry():
    assert set(ALLOWED_TRANSITIONS.keys()) == set(ReferralStatus)


def _referral(status, specialty="Cardiology"):
    return Referral(
        id=1,
        patient_id=1,
        origin_facility_id=1,
        status=status,
        priority=ReferralPriority.ROUTINE,
        specialty_requested=specialty,
    )


def _provider(specialty="Cardiology", accepting=True):
    return Provider(
        id=1,
        facility_id=1,
        npi="1234567890",
        full_name="Dr. Test",
        specialty=specialty,
        accepting_new_patients=accepting,
    )


def test_validate_assignment_passes_for_open_matching_provider():
    validate_assignment(_referral(ReferralStatus.SUBMITTED), _provider())


def test_validate_assignment_rejects_wrong_status():
    with pytest.raises(ReferralRuleViolation):
        validate_assignment(_referral(ReferralStatus.DRAFT), _provider())


def test_validate_assignment_rejects_specialty_mismatch():
    with pytest.raises(ReferralRuleViolation):
        validate_assignment(
            _referral(ReferralStatus.SUBMITTED, specialty="Cardiology"),
            _provider(specialty="Neurology"),
        )


def test_validate_assignment_rejects_provider_not_accepting():
    with pytest.raises(ReferralRuleViolation):
        validate_assignment(
            _referral(ReferralStatus.SUBMITTED), _provider(accepting=False)
        )


def test_validate_assignment_specialty_match_is_case_insensitive():
    validate_assignment(
        _referral(ReferralStatus.SUBMITTED, specialty="cardiology"),
        _provider(specialty="CARDIOLOGY"),
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.referral_rules'`.

- [ ] **Step 3: Implement `app/referral_rules.py`**

Create `app/referral_rules.py`:
```python
"""Referral lifecycle rules: the status transition state machine and
provider-assignment validation.

Pure functions — no FastAPI, no database session — so they can be tested
and reasoned about on their own. app/main.py is the only caller.
"""

from __future__ import annotations

from app.models import Provider, Referral, ReferralStatus


class ReferralRuleViolation(Exception):
    """Raised when a requested change violates a referral lifecycle rule."""


ALLOWED_TRANSITIONS: dict[ReferralStatus, set[ReferralStatus]] = {
    ReferralStatus.DRAFT: {ReferralStatus.SUBMITTED, ReferralStatus.CANCELLED},
    ReferralStatus.SUBMITTED: {
        ReferralStatus.ACCEPTED,
        ReferralStatus.REJECTED,
        ReferralStatus.CANCELLED,
    },
    ReferralStatus.ACCEPTED: {ReferralStatus.SCHEDULED, ReferralStatus.CANCELLED},
    ReferralStatus.SCHEDULED: {ReferralStatus.COMPLETED, ReferralStatus.CANCELLED},
    ReferralStatus.COMPLETED: set(),
    ReferralStatus.CANCELLED: set(),
    ReferralStatus.REJECTED: set(),
}

# Referral must be in one of these statuses before a provider can be
# assigned — not yet submitted (DRAFT) or already resolved (terminal).
ASSIGNABLE_STATUSES = {ReferralStatus.SUBMITTED, ReferralStatus.ACCEPTED}


def validate_transition(current: ReferralStatus, target: ReferralStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ReferralRuleViolation(
            f"cannot transition referral from '{current.value}' to '{target.value}'"
        )


def validate_assignment(referral: Referral, provider: Provider) -> None:
    if referral.status not in ASSIGNABLE_STATUSES:
        raise ReferralRuleViolation(
            f"referral is not open for assignment (status='{referral.status.value}')"
        )
    if provider.specialty.strip().lower() != referral.specialty_requested.strip().lower():
        raise ReferralRuleViolation(
            f"provider specialty '{provider.specialty}' does not match "
            f"requested specialty '{referral.specialty_requested}'"
        )
    if not provider.accepting_new_patients:
        raise ReferralRuleViolation(
            f"provider {provider.id} is not accepting new patients"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: `PASSED` for all tests in `test_referral_rules.py` (plus the smoke test).

Tear down: `docker compose -p careroute-test -f docker-compose.test.yml down -v`

- [ ] **Step 5: Commit**

```bash
git add app/referral_rules.py tests/test_referral_rules.py
git commit -m "feat(careroute): add referral transition state machine and assignment rules"
```

---

## Task 3: Request/response schemas

**Files:**
- Create: `app/schemas.py`
- Create: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_schemas.py`:
```python
"""Contract tests for the request schemas — confirms defaults and rejects
malformed input the way the API is documented to (422 territory)."""

import pytest
from pydantic import ValidationError

from app.models import ReferralPriority
from app.schemas import PatientCreate, ReferralCreate


def test_patient_create_requires_mrn_full_name_and_dob():
    with pytest.raises(ValidationError):
        PatientCreate(full_name="Jane Test")


def test_patient_create_accepts_minimal_payload():
    patient = PatientCreate(
        mrn="MRN-1", full_name="Jane Test", date_of_birth="1990-01-01"
    )
    assert patient.phone is None
    assert patient.email is None


def test_referral_create_defaults_priority_to_routine():
    referral = ReferralCreate(
        patient_id=1,
        origin_facility_id=1,
        specialty_requested="Cardiology",
        actor="dr.test",
    )
    assert referral.priority == ReferralPriority.ROUTINE


def test_referral_create_rejects_invalid_priority():
    with pytest.raises(ValidationError):
        ReferralCreate(
            patient_id=1,
            origin_facility_id=1,
            specialty_requested="Cardiology",
            actor="dr.test",
            priority="not-a-real-priority",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.schemas'`.

- [ ] **Step 3: Implement `app/schemas.py`**

Create `app/schemas.py`:
```python
"""Request/response models for the write endpoints.

Separate from app/models.py (the SQLAlchemy ORM layer): these describe the
HTTP contract, not the database schema. `Out` models read straight off ORM
instances via `from_attributes=True`.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models import ReferralPriority, ReferralStatus


class PatientCreate(BaseModel):
    mrn: str
    full_name: str
    date_of_birth: date
    phone: str | None = None
    email: str | None = None


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mrn: str
    full_name: str
    date_of_birth: date
    phone: str | None
    email: str | None
    created_at: datetime


class ReferralCreate(BaseModel):
    patient_id: int
    origin_facility_id: int
    specialty_requested: str
    priority: ReferralPriority = ReferralPriority.ROUTINE
    reason: str | None = None
    actor: str


class ReferralOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    origin_facility_id: int
    assigned_provider_id: int | None
    status: ReferralStatus
    priority: ReferralPriority
    specialty_requested: str
    reason: str | None
    created_at: datetime
    updated_at: datetime


class ReferralEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: ReferralStatus | None
    to_status: ReferralStatus
    actor: str
    note: str | None
    occurred_at: datetime


class ReferralWithEvents(ReferralOut):
    events: list[ReferralEventOut]


class ReferralAssignRequest(BaseModel):
    provider_id: int
    actor: str
    note: str | None = None


class ReferralStatusRequest(BaseModel):
    to_status: ReferralStatus
    actor: str
    note: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: `PASSED` for all tests in `test_schemas.py` (plus everything from Tasks 1–2).

Tear down: `docker compose -p careroute-test -f docker-compose.test.yml down -v`

- [ ] **Step 5: Commit**

```bash
git add app/schemas.py tests/test_schemas.py
git commit -m "feat(careroute): add request/response schemas for write endpoints"
```

---

## Task 4: `POST /patients`

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_patients.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_patients.py`:
```python
"""Tests for POST /patients."""


def test_create_patient_returns_201_with_patient(client):
    response = client.post(
        "/patients",
        json={
            "mrn": "MRN-100",
            "full_name": "Jane Test",
            "date_of_birth": "1990-01-01",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["mrn"] == "MRN-100"
    assert body["full_name"] == "Jane Test"
    assert body["phone"] is None
    assert "id" in body


def test_create_patient_rejects_duplicate_mrn(client):
    payload = {
        "mrn": "MRN-DUP",
        "full_name": "First Patient",
        "date_of_birth": "1990-01-01",
    }
    first = client.post("/patients", json=payload)
    assert first.status_code == 201

    second = client.post("/patients", json={**payload, "full_name": "Second Patient"})
    assert second.status_code == 409


def test_create_patient_requires_mrn(client):
    response = client.post(
        "/patients", json={"full_name": "No MRN", "date_of_birth": "1990-01-01"}
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: FAIL — `404 Not Found` (route doesn't exist yet).

- [ ] **Step 3: Add the route**

Modify `app/main.py`. Change the import line:
```python
from fastapi import Depends, FastAPI
```
to:
```python
from fastapi import Depends, FastAPI, HTTPException, status
```

Change:
```python
from sqlalchemy.exc import SQLAlchemyError
```
to:
```python
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
```

After the existing imports (below `from app.models import (...)`), add:
```python
from app.schemas import PatientCreate, PatientOut
```

At the end of the file, after the `worklist` function, add:
```python


@app.post("/patients", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: PatientCreate, session: Session = Depends(get_session)
) -> Patient:
    """Create a patient. 409s if the MRN is already in use."""
    patient = Patient(**payload.model_dump())
    session.add(patient)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"patient with mrn '{payload.mrn}' already exists",
        ) from exc
    session.refresh(patient)
    return patient
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: `PASSED` for all tests in `test_patients.py` (plus everything from Tasks 1–3).

Tear down: `docker compose -p careroute-test -f docker-compose.test.yml down -v`

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_patients.py
git commit -m "feat(careroute): add POST /patients"
```

---

## Task 5: `POST /referrals`

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_referrals_create.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_referrals_create.py`:
```python
"""Tests for POST /referrals."""

from app.models import ReferralEvent


def test_create_referral_starts_in_draft_status(client, facility, patient):
    response = client.post(
        "/referrals",
        json={
            "patient_id": patient.id,
            "origin_facility_id": facility.id,
            "specialty_requested": "Cardiology",
            "actor": "dr.test",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["priority"] == "routine"
    assert body["assigned_provider_id"] is None


def test_create_referral_404s_for_missing_patient(client, facility):
    response = client.post(
        "/referrals",
        json={
            "patient_id": 999999,
            "origin_facility_id": facility.id,
            "specialty_requested": "Cardiology",
            "actor": "dr.test",
        },
    )
    assert response.status_code == 404


def test_create_referral_404s_for_missing_facility(client, patient):
    response = client.post(
        "/referrals",
        json={
            "patient_id": patient.id,
            "origin_facility_id": 999999,
            "specialty_requested": "Cardiology",
            "actor": "dr.test",
        },
    )
    assert response.status_code == 404


def test_create_referral_writes_initial_draft_event(client, facility, patient, db):
    response = client.post(
        "/referrals",
        json={
            "patient_id": patient.id,
            "origin_facility_id": facility.id,
            "specialty_requested": "Cardiology",
            "actor": "dr.test",
            "reason": "chest pain",
        },
    )
    referral_id = response.json()["id"]
    events = (
        db.query(ReferralEvent)
        .filter(ReferralEvent.referral_id == referral_id)
        .all()
    )
    assert len(events) == 1
    assert events[0].from_status is None
    assert events[0].to_status.value == "draft"
    assert events[0].actor == "dr.test"
    assert events[0].note == "chest pain"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: FAIL — `404 Not Found` (route doesn't exist yet).

- [ ] **Step 3: Add the route**

Modify `app/main.py`. Change:
```python
from app.schemas import PatientCreate, PatientOut
```
to:
```python
from app.schemas import PatientCreate, PatientOut, ReferralCreate, ReferralOut
```

After the `create_patient` function, add:
```python


@app.post("/referrals", response_model=ReferralOut, status_code=status.HTTP_201_CREATED)
def create_referral(
    payload: ReferralCreate, session: Session = Depends(get_session)
) -> Referral:
    """Submit a new referral. Starts in DRAFT status; logs the first
    referral_event (from_status=null -> DRAFT)."""
    if session.get(Patient, payload.patient_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"patient {payload.patient_id} not found",
        )
    if session.get(Facility, payload.origin_facility_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"facility {payload.origin_facility_id} not found",
        )

    referral = Referral(
        patient_id=payload.patient_id,
        origin_facility_id=payload.origin_facility_id,
        specialty_requested=payload.specialty_requested,
        priority=payload.priority,
        reason=payload.reason,
        status=ReferralStatus.DRAFT,
    )
    session.add(referral)
    session.flush()  # assigns referral.id for the event below

    session.add(
        ReferralEvent(
            referral_id=referral.id,
            from_status=None,
            to_status=ReferralStatus.DRAFT,
            actor=payload.actor,
            note=payload.reason,
        )
    )
    session.commit()
    session.refresh(referral)
    return referral
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: `PASSED` for all tests in `test_referrals_create.py` (plus everything from Tasks 1–4).

Tear down: `docker compose -p careroute-test -f docker-compose.test.yml down -v`

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_referrals_create.py
git commit -m "feat(careroute): add POST /referrals"
```

---

## Task 6: `POST /referrals/{id}/assign`

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_referrals_assign.py`

This task also wires up the `ReferralRuleViolation` → `409` exception handler, since assignment is the first endpoint that raises it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_referrals_assign.py`:
```python
"""Tests for POST /referrals/{id}/assign."""

from app.models import Provider, Referral, ReferralPriority, ReferralStatus


def test_assign_sets_provider_on_open_referral(client, submitted_referral, provider):
    response = client.post(
        f"/referrals/{submitted_referral.id}/assign",
        json={"provider_id": provider.id, "actor": "router"},
    )
    assert response.status_code == 200
    assert response.json()["assigned_provider_id"] == provider.id


def test_assign_404s_for_missing_referral(client, provider):
    response = client.post(
        "/referrals/999999/assign",
        json={"provider_id": provider.id, "actor": "router"},
    )
    assert response.status_code == 404


def test_assign_404s_for_missing_provider(client, submitted_referral):
    response = client.post(
        f"/referrals/{submitted_referral.id}/assign",
        json={"provider_id": 999999, "actor": "router"},
    )
    assert response.status_code == 404


def test_assign_409s_when_referral_not_open(client, db, facility, patient, provider):
    draft_referral = Referral(
        patient_id=patient.id,
        origin_facility_id=facility.id,
        specialty_requested="Cardiology",
        priority=ReferralPriority.ROUTINE,
        status=ReferralStatus.DRAFT,
    )
    db.add(draft_referral)
    db.commit()
    db.refresh(draft_referral)

    response = client.post(
        f"/referrals/{draft_referral.id}/assign",
        json={"provider_id": provider.id, "actor": "router"},
    )
    assert response.status_code == 409


def test_assign_409s_on_specialty_mismatch(client, db, submitted_referral, facility):
    mismatched_provider = Provider(
        facility_id=facility.id,
        npi="9999999999",
        full_name="Dr. Wrong Specialty",
        specialty="Neurology",
        accepting_new_patients=True,
    )
    db.add(mismatched_provider)
    db.commit()
    db.refresh(mismatched_provider)

    response = client.post(
        f"/referrals/{submitted_referral.id}/assign",
        json={"provider_id": mismatched_provider.id, "actor": "router"},
    )
    assert response.status_code == 409


def test_assign_409s_when_provider_not_accepting(client, db, submitted_referral, facility):
    full_provider = Provider(
        facility_id=facility.id,
        npi="8888888888",
        full_name="Dr. Full",
        specialty="Cardiology",
        accepting_new_patients=False,
    )
    db.add(full_provider)
    db.commit()
    db.refresh(full_provider)

    response = client.post(
        f"/referrals/{submitted_referral.id}/assign",
        json={"provider_id": full_provider.id, "actor": "router"},
    )
    assert response.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: FAIL — `404 Not Found` (route doesn't exist yet).

- [ ] **Step 3: Add the exception handler and the route**

Modify `app/main.py`. Change:
```python
from fastapi import Depends, FastAPI, HTTPException, status
```
to:
```python
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
```

Change:
```python
from app.schemas import PatientCreate, PatientOut, ReferralCreate, ReferralOut
```
to:
```python
from app.referral_rules import ReferralRuleViolation, validate_assignment
from app.schemas import (
    PatientCreate,
    PatientOut,
    ReferralAssignRequest,
    ReferralCreate,
    ReferralOut,
)
```

Change:
```python
app = FastAPI(title="CareRoute")
```
to:
```python
app = FastAPI(title="CareRoute")


@app.exception_handler(ReferralRuleViolation)
def handle_referral_rule_violation(
    request: Request, exc: ReferralRuleViolation
) -> JSONResponse:
    """Referral lifecycle rule violations (bad transition, bad assignment)
    are client errors, not server errors — map them to 409."""
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)}
    )
```

After the `create_referral` function, add:
```python


@app.post("/referrals/{referral_id}/assign", response_model=ReferralOut)
def assign_referral(
    referral_id: int,
    payload: ReferralAssignRequest,
    session: Session = Depends(get_session),
) -> Referral:
    """Assign a provider to a referral. Validated by
    referral_rules.validate_assignment (status/specialty/capacity)."""
    referral = session.get(Referral, referral_id)
    if referral is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"referral {referral_id} not found",
        )
    provider = session.get(Provider, payload.provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"provider {payload.provider_id} not found",
        )

    validate_assignment(referral, provider)

    referral.assigned_provider_id = provider.id
    session.commit()
    session.refresh(referral)
    return referral
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: `PASSED` for all tests in `test_referrals_assign.py` (plus everything from Tasks 1–5).

Tear down: `docker compose -p careroute-test -f docker-compose.test.yml down -v`

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_referrals_assign.py
git commit -m "feat(careroute): add POST /referrals/{id}/assign"
```

---

## Task 7: `POST /referrals/{id}/status`

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_referrals_status.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_referrals_status.py`:
```python
"""Tests for POST /referrals/{id}/status."""

from app.models import ReferralEvent


def test_valid_transition_updates_status_and_logs_event(client, db, submitted_referral):
    response = client.post(
        f"/referrals/{submitted_referral.id}/status",
        json={"to_status": "accepted", "actor": "dr.test", "note": "looks good"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"

    events = (
        db.query(ReferralEvent)
        .filter(ReferralEvent.referral_id == submitted_referral.id)
        .all()
    )
    assert len(events) == 1
    assert events[0].from_status.value == "submitted"
    assert events[0].to_status.value == "accepted"
    assert events[0].note == "looks good"


def test_invalid_transition_returns_409(client, submitted_referral):
    response = client.post(
        f"/referrals/{submitted_referral.id}/status",
        json={"to_status": "completed", "actor": "dr.test"},
    )
    assert response.status_code == 409


def test_status_404s_for_missing_referral(client):
    response = client.post(
        "/referrals/999999/status",
        json={"to_status": "accepted", "actor": "dr.test"},
    )
    assert response.status_code == 404


def test_terminal_status_rejects_further_transitions(client, submitted_referral):
    first = client.post(
        f"/referrals/{submitted_referral.id}/status",
        json={"to_status": "rejected", "actor": "dr.test"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/referrals/{submitted_referral.id}/status",
        json={"to_status": "submitted", "actor": "dr.test"},
    )
    assert second.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: FAIL — `404 Not Found` (route doesn't exist yet).

- [ ] **Step 3: Add the route**

Modify `app/main.py`. Change:
```python
from app.referral_rules import ReferralRuleViolation, validate_assignment
from app.schemas import (
    PatientCreate,
    PatientOut,
    ReferralAssignRequest,
    ReferralCreate,
    ReferralOut,
)
```
to:
```python
from app.referral_rules import (
    ReferralRuleViolation,
    validate_assignment,
    validate_transition,
)
from app.schemas import (
    PatientCreate,
    PatientOut,
    ReferralAssignRequest,
    ReferralCreate,
    ReferralOut,
    ReferralStatusRequest,
)
```

After the `assign_referral` function, add:
```python


@app.post("/referrals/{referral_id}/status", response_model=ReferralOut)
def update_referral_status(
    referral_id: int,
    payload: ReferralStatusRequest,
    session: Session = Depends(get_session),
) -> Referral:
    """Transition a referral's status. Validated by
    referral_rules.validate_transition; logs a referral_event on success."""
    referral = session.get(Referral, referral_id)
    if referral is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"referral {referral_id} not found",
        )

    validate_transition(referral.status, payload.to_status)

    session.add(
        ReferralEvent(
            referral_id=referral.id,
            from_status=referral.status,
            to_status=payload.to_status,
            actor=payload.actor,
            note=payload.note,
        )
    )
    referral.status = payload.to_status
    session.commit()
    session.refresh(referral)
    return referral
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: `PASSED` for all tests in `test_referrals_status.py` (plus everything from Tasks 1–6).

Tear down: `docker compose -p careroute-test -f docker-compose.test.yml down -v`

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_referrals_status.py
git commit -m "feat(careroute): add POST /referrals/{id}/status"
```

---

## Task 8: `GET /referrals/{id}`

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_referrals_get.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_referrals_get.py`:
```python
"""Tests for GET /referrals/{id}."""


def test_get_referral_includes_event_history(client, submitted_referral):
    # submitted_referral is inserted directly via SQLAlchemy in the
    # fixture, so it has no referral_events rows yet — build history
    # through the API first.
    client.post(
        f"/referrals/{submitted_referral.id}/status",
        json={"to_status": "accepted", "actor": "dr.test"},
    )
    client.post(
        f"/referrals/{submitted_referral.id}/status",
        json={"to_status": "scheduled", "actor": "dr.test"},
    )

    response = client.get(f"/referrals/{submitted_referral.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "scheduled"
    assert len(body["events"]) == 2
    assert body["events"][0]["to_status"] == "accepted"
    assert body["events"][1]["to_status"] == "scheduled"


def test_get_referral_404s_for_missing_referral(client):
    response = client.get("/referrals/999999")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: FAIL — `405 Method Not Allowed` (path exists for POST variants but not a bare GET on `/referrals/{id}`, or 404 depending on route matching — either way, not the `200` the test expects).

- [ ] **Step 3: Add the route**

Modify `app/main.py`. Change:
```python
from app.schemas import (
    PatientCreate,
    PatientOut,
    ReferralAssignRequest,
    ReferralCreate,
    ReferralOut,
    ReferralStatusRequest,
)
```
to:
```python
from app.schemas import (
    PatientCreate,
    PatientOut,
    ReferralAssignRequest,
    ReferralCreate,
    ReferralEventOut,
    ReferralOut,
    ReferralStatusRequest,
    ReferralWithEvents,
)
```

After the `update_referral_status` function, add:
```python


@app.get("/referrals/{referral_id}", response_model=ReferralWithEvents)
def get_referral(
    referral_id: int, session: Session = Depends(get_session)
) -> ReferralWithEvents:
    """Fetch a referral plus its full status-change history."""
    referral = session.get(Referral, referral_id)
    if referral is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"referral {referral_id} not found",
        )
    events = (
        session.execute(
            select(ReferralEvent)
            .where(ReferralEvent.referral_id == referral_id)
            .order_by(ReferralEvent.occurred_at)
        )
        .scalars()
        .all()
    )
    return ReferralWithEvents(
        **ReferralOut.model_validate(referral).model_dump(),
        events=[ReferralEventOut.model_validate(e) for e in events],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: `PASSED` for all tests in `test_referrals_get.py` (plus everything from Tasks 1–7).

Tear down: `docker compose -p careroute-test -f docker-compose.test.yml down -v`

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_referrals_get.py
git commit -m "feat(careroute): add GET /referrals/{id}"
```

---

## Task 9: End-to-end lifecycle test

**Files:**
- Create: `tests/test_referral_lifecycle.py`

Ties every endpoint from Tasks 4–8 together in one flow, the way a real caller would use the API. This is the "happy path" the spec's Testing section calls for.

- [ ] **Step 1: Write the test**

Create `tests/test_referral_lifecycle.py`:
```python
"""End-to-end happy path: create patient -> create referral -> submit ->
assign -> transition to completed -> fetch full history. Exercises every
new endpoint together."""


def test_full_referral_lifecycle(client, facility, provider):
    patient_response = client.post(
        "/patients",
        json={
            "mrn": "MRN-E2E-001",
            "full_name": "End To End Patient",
            "date_of_birth": "1985-06-15",
        },
    )
    assert patient_response.status_code == 201
    patient_id = patient_response.json()["id"]

    referral_response = client.post(
        "/referrals",
        json={
            "patient_id": patient_id,
            "origin_facility_id": facility.id,
            "specialty_requested": "Cardiology",
            "priority": "urgent",
            "reason": "abnormal EKG",
            "actor": "dr.intake",
        },
    )
    assert referral_response.status_code == 201
    referral = referral_response.json()
    assert referral["status"] == "draft"
    referral_id = referral["id"]

    submit_response = client.post(
        f"/referrals/{referral_id}/status",
        json={"to_status": "submitted", "actor": "dr.intake"},
    )
    assert submit_response.status_code == 200

    assign_response = client.post(
        f"/referrals/{referral_id}/assign",
        json={"provider_id": provider.id, "actor": "router"},
    )
    assert assign_response.status_code == 200
    assert assign_response.json()["assigned_provider_id"] == provider.id

    for to_status in ("accepted", "scheduled", "completed"):
        transition = client.post(
            f"/referrals/{referral_id}/status",
            json={"to_status": to_status, "actor": "dr.specialist"},
        )
        assert transition.status_code == 200, transition.json()
        assert transition.json()["status"] == to_status

    final = client.get(f"/referrals/{referral_id}")
    assert final.status_code == 200
    body = final.json()
    assert body["status"] == "completed"
    assert body["assigned_provider_id"] == provider.id
    assert [e["to_status"] for e in body["events"]] == [
        "draft",
        "submitted",
        "accepted",
        "scheduled",
        "completed",
    ]
```

- [ ] **Step 2: Run it**

Run:
```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
```
Expected: `PASSED` for `test_referral_lifecycle.py`, and the full suite (all tasks) reports something like `33 passed`.

Tear down: `docker compose -p careroute-test -f docker-compose.test.yml down -v`

- [ ] **Step 3: Commit**

```bash
git add tests/test_referral_lifecycle.py
git commit -m "test(careroute): add end-to-end referral lifecycle test"
```

---

## Task 10: Manual verification against the dev stack, docs, and final check

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rebuild and restart the dev stack**

```bash
cd "/Users/kyleharrington/Desktop/AI/Docker/CareRoute"
docker compose up -d --build
```
Expected: `db` healthy, `migrate` exits 0, `api` healthy. Seed data from prior sessions is untouched (this only rebuilds the image; the named volume persists).

- [ ] **Step 2: Exercise the new endpoints against the live dev stack**

```bash
# Create a patient
curl -s -X POST http://localhost:8000/patients \
  -H 'Content-Type: application/json' \
  -d '{"mrn":"MRN-MANUAL-001","full_name":"Manual Test Patient","date_of_birth":"1988-03-02"}'

# Create a referral for that patient against seeded facility 1
curl -s -X POST http://localhost:8000/referrals \
  -H 'Content-Type: application/json' \
  -d '{"patient_id":<id from previous response>,"origin_facility_id":1,"specialty_requested":"Cardiology","actor":"manual-test"}'

# Submit it
curl -s -X POST http://localhost:8000/referrals/<referral id>/status \
  -H 'Content-Type: application/json' \
  -d '{"to_status":"submitted","actor":"manual-test"}'

# Find a seeded Cardiology provider who's accepting patients, then assign
curl -s "http://localhost:8000/referrals/worklist" | head -c 500
curl -s -X POST http://localhost:8000/referrals/<referral id>/assign \
  -H 'Content-Type: application/json' \
  -d '{"provider_id":<a cardiology provider id>,"actor":"manual-test"}'

# Fetch it with full history
curl -s http://localhost:8000/referrals/<referral id>
```
Expected: each call returns the appropriate `200`/`201` with the fields described in the spec, and the final `GET` shows the full event history (`draft` → `submitted`).

- [ ] **Step 3: Re-run the vulnerability scan**

```bash
docker scout quickview careroute:local
```
Expected: unchanged from before this feature — `0C` critical, "No fixable critical or high vulnerabilities" policy still passes. (No new production dependencies were added; `requirements-dev.txt` never ships in `careroute:local`.)

- [ ] **Step 4: Update the README**

Modify `README.md`. In the `## Endpoints` table, change:
```markdown
| Path | Purpose |
|---|---|
| `GET /health` | Liveness. Deliberately does not touch the database |
| `GET /ready` | Readiness. Reports whether Postgres is reachable |
| `GET /stats` | Row counts per table — used by the restore drill |
| `GET /referrals/worklist` | Open referrals, most urgent first, then oldest first |
```
to:
```markdown
| Path | Purpose |
|---|---|
| `GET /health` | Liveness. Deliberately does not touch the database |
| `GET /ready` | Readiness. Reports whether Postgres is reachable |
| `GET /stats` | Row counts per table — used by the restore drill |
| `GET /referrals/worklist` | Open referrals, most urgent first, then oldest first |
| `POST /patients` | Create a patient. 409 on duplicate `mrn` |
| `POST /referrals` | Submit a referral (starts in `draft`). 404 on missing patient/facility |
| `POST /referrals/{id}/assign` | Assign a provider. 409 on closed referral, specialty mismatch, or provider not accepting patients |
| `POST /referrals/{id}/status` | Transition status. 409 on an illegal transition |
| `GET /referrals/{id}` | A referral plus its full status-change history |
```

Immediately after that table, add:
```markdown
No endpoint requires authentication — matches the rest of the API. Every
write endpoint takes an `actor` field (free text: who's making the change)
which is what shows up in `referral_events`.

Assigning a provider does not itself write a `referral_event` —
`referral_events` is specifically a status-transition log, not a general
audit trail.
```

Add a new section after `## Schema changes` and before `## Seed data`:
```markdown
---

## Running tests

Tests run against their own ephemeral Postgres — never the dev database —
under a separate Compose project name so the two stacks never collide:

```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
docker compose -p careroute-test -f docker-compose.test.yml down -v
```

Test-only dependencies (`pytest`, `httpx`) live in `requirements-dev.txt`
and a dedicated `test` Dockerfile stage — neither ships in the production
image built by `docker compose build`.
```

In the `## Verified` section at the bottom of the file, add two bullets after the existing ones:
```markdown
- Referral write endpoints: full lifecycle (create patient → submit
  referral → assign provider → transition through to completed) exercised
  both by the pytest suite and manually against the live dev stack
- Business rules reject what they should: illegal status transitions,
  assigning a provider with the wrong specialty, assigning one that isn't
  accepting new patients, and assigning to a referral that isn't open —
  all return 409
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(careroute): document referral write endpoints and test workflow"
```

---

## Plan Self-Review Notes

- **Spec coverage:** all 5 endpoints, the transition state machine, assignment validation, no-auth decision, `app/schemas.py` + `app/referral_rules.py` split, isolated test infra (separate compose project, ephemeral DB, dedicated Dockerfile stage, `requirements-dev.txt`), and the manual + automated verification steps from the spec are each covered by a task above.
- **Type/name consistency verified across tasks:** `ReferralRuleViolation`, `validate_transition`, `validate_assignment`, `ALLOWED_TRANSITIONS`, `ASSIGNABLE_STATUSES` (Task 2) match their usage in Task 6/7 (`app/main.py`). Schema class names (`PatientCreate`, `PatientOut`, `ReferralCreate`, `ReferralOut`, `ReferralEventOut`, `ReferralWithEvents`, `ReferralAssignRequest`, `ReferralStatusRequest`, Task 3) match every import in Tasks 4–8. Fixture names (`facility`, `provider`, `patient`, `submitted_referral`, `db`, `client`, Task 1) match every test's parameter list in Tasks 2–9.
- **Known risk called out in-line:** Task 1 Step 3's `python -m ensurepip --upgrade` in the `test-deps` stage re-installs pip after `builder` uninstalled it — if this fails, Task 1 Step 6 (the first real build of the test stack) surfaces it immediately, before any feature work is built on top.
