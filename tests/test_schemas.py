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
