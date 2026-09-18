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
