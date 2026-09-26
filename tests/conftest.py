"""Shared pytest fixtures.

Runs against the ephemeral Postgres started by docker-compose.test.yml.
`clean_tables` is autouse so every test starts with empty tables — no test
depends on another test's data, and none of this touches the dev stack's
seeded database (a separate container entirely). It truncates through the
schema owner's connection (OWNER_DATABASE_URL), because the app role the tests
otherwise run as has no TRUNCATE, and RESTART IDENTITY needs sequence
ownership (ADR-0010).

`client` is authenticated as a coordinator (the role allowed to do
everything), so endpoint tests exercise business rules without repeating
auth setup. Auth itself — 401s, 403s, the role matrix — is covered in
test_auth.py via `anon_client` and `client_as`.
"""

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.auth import create_access_token, hash_password
from app.db import SessionLocal, engine
from app.main import app
from app.models import (
    Facility,
    Patient,
    Provider,
    Referral,
    ReferralPriority,
    ReferralStatus,
    User,
    UserRole,
)

TEST_PASSWORD = "correct-horse-battery-staple"
COORDINATOR_EMAIL = "coordinator@test.careroute"


# Falls back to the app engine when unset (e.g. an older stack without roles).
owner_engine = (
    create_engine(os.environ["OWNER_DATABASE_URL"])
    if os.environ.get("OWNER_DATABASE_URL")
    else engine
)


@pytest.fixture(autouse=True)
def clean_tables():
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE referral_events, referrals, patients, "
                "providers, facilities, users RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture()
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def make_user(db):
    """Factory: persist a user with the given role and TEST_PASSWORD."""

    def _make(role: UserRole, email: str | None = None, **kwargs) -> User:
        user = User(
            email=email or f"{role.value}@test.careroute",
            full_name=f"Test {role.value.title()}",
            password_hash=hash_password(TEST_PASSWORD),
            role=role,
            **kwargs,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make


@pytest.fixture()
def client_as(make_user):
    """Factory: a TestClient carrying a bearer token for a new user of `role`."""

    def _client(role: UserRole) -> TestClient:
        token = create_access_token(make_user(role))
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    return _client


@pytest.fixture()
def client(client_as):
    return client_as(UserRole.COORDINATOR)


@pytest.fixture()
def anon_client():
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
