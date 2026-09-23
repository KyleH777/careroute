"""Tests for POST /referrals/{id}/status."""

from app.models import ReferralEvent


def test_valid_transition_updates_status_and_logs_event(client, db, submitted_referral):
    response = client.post(
        f"/referrals/{submitted_referral.id}/status",
        json={"to_status": "accepted", "note": "looks good"},
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
        json={"to_status": "completed"},
    )
    assert response.status_code == 409


def test_status_404s_for_missing_referral(client):
    response = client.post(
        "/referrals/999999/status",
        json={"to_status": "accepted"},
    )
    assert response.status_code == 404


def test_terminal_status_rejects_further_transitions(client, submitted_referral):
    first = client.post(
        f"/referrals/{submitted_referral.id}/status",
        json={"to_status": "rejected"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/referrals/{submitted_referral.id}/status",
        json={"to_status": "submitted"},
    )
    assert second.status_code == 409
