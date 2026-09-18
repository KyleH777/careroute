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
