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
