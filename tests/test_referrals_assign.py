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


def test_assign_409s_when_provider_not_accepting(
    client, db, submitted_referral, facility
):
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
