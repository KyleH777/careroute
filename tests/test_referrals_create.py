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
        db.query(ReferralEvent).filter(ReferralEvent.referral_id == referral_id).all()
    )
    assert len(events) == 1
    assert events[0].from_status is None
    assert events[0].to_status.value == "draft"
    assert events[0].actor == "dr.test"
    assert events[0].note == "chest pain"
