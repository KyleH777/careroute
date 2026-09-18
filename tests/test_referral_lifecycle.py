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
