"""PHI read/write access auditing (AUDIT-01, AUDIT-02; ADR-0014)."""

import json
import logging
import os
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app import access_audit
from app.auth import create_access_token
from app.main import app
from app.models import (
    Patient,
    Provider,
    RecordAccess,
    Referral,
    ReferralPriority,
    ReferralStatus,
    UserRole,
)
from app.observability import JsonFormatter

COORD = "coordinator@test.careroute"


def _rows(db):
    db.expire_all()
    return list(db.execute(select(RecordAccess).order_by(RecordAccess.id)).scalars())


def _audit_lines(caplog, action=None):
    lines = [
        json.loads(JsonFormatter().format(r))
        for r in caplog.records
        if r.name == "careroute.audit"
    ]
    if action is not None:
        lines = [ln for ln in lines if ln["action"] == action]
    return lines


# (method, path template) -> (expected action, builder(ctx) -> (method, url, json))
BEHAVIOUR = {
    ("GET", "/referrals/worklist"): (
        "referral.list",
        lambda c: ("GET", "/referrals/worklist", None),
    ),
    ("GET", "/referrals/{referral_id}"): (
        "referral.read",
        lambda c: ("GET", f"/referrals/{c.referral.id}", None),
    ),
    ("POST", "/patients"): (
        "patient.create",
        lambda c: (
            "POST",
            "/patients",
            {
                "mrn": "MRN-NEW-1",
                "full_name": "New Person",
                "date_of_birth": "2000-02-02",
            },
        ),
    ),
    ("POST", "/referrals"): (
        "referral.create",
        lambda c: (
            "POST",
            "/referrals",
            {
                "patient_id": c.patient.id,
                "origin_facility_id": c.facility.id,
                "specialty_requested": "Cardiology",
                "reason": "r",
            },
        ),
    ),
    ("POST", "/referrals/{referral_id}/assign"): (
        "referral.assign",
        lambda c: (
            "POST",
            f"/referrals/{c.referral.id}/assign",
            {"provider_id": c.provider.id},
        ),
    ),
    ("POST", "/referrals/{referral_id}/status"): (
        "referral.status",
        lambda c: (
            "POST",
            f"/referrals/{c.referral.id}/status",
            {"to_status": "accepted"},
        ),
    ),
}


@pytest.mark.parametrize("key", list(BEHAVIOUR), ids=lambda k: f"{k[0]} {k[1]}")
def test_route_writes_access_rows(
    key, client, db, patient, facility, provider, submitted_referral, caplog
):
    caplog.set_level(logging.INFO, logger="careroute.audit")
    action, build = BEHAVIOUR[key]
    ctx = SimpleNamespace(
        patient=patient,
        facility=facility,
        provider=provider,
        referral=submitted_referral,
    )
    method, url, body = build(ctx)
    resp = client.request(method, url, json=body)
    assert 200 <= resp.status_code < 300, resp.text
    data = resp.json()
    items = data if isinstance(data, list) else [data]

    if action == "patient.create":
        want_ref: set[int] = set()
        want_pat = {i["id"] for i in items}
    else:
        want_ref = {i["id"] for i in items}
        want_pat = {i["patient_id"] for i in items}

    rows = _rows(db)
    assert rows
    for r in rows:
        assert r.action == action
        assert r.actor == COORD
        assert r.request_id == resp.headers["X-Request-ID"]
        assert r.occurred_at is not None
    assert {r.referral_id for r in rows if r.referral_id is not None} == want_ref
    assert {r.patient_id for r in rows if r.patient_id is not None} == want_pat

    lines = _audit_lines(caplog, action)
    assert len(lines) == 1
    assert lines[0]["referral_ids"] == sorted(want_ref)
    assert lines[0]["patient_ids"] == sorted(want_pat)
    assert lines[0]["request_id"] == resp.headers["X-Request-ID"]
    assert lines[0]["actor"] == COORD


def _submitted(db, facility, patient):
    r = Referral(
        patient_id=patient.id,
        origin_facility_id=facility.id,
        specialty_requested="Cardiology",
        priority=ReferralPriority.ROUTINE,
        status=ReferralStatus.SUBMITTED,
    )
    db.add(r)
    db.commit()
    return r


def test_worklist_one_row_per_referral(client, db, facility, patient, caplog):
    caplog.set_level(logging.INFO, logger="careroute.audit")
    other = Patient(mrn="MRN-OTHER", full_name="Other", date_of_birth=date(1980, 5, 5))
    db.add(other)
    db.commit()
    r1 = _submitted(db, facility, patient)
    r2 = _submitted(db, facility, patient)
    r3 = _submitted(db, facility, other)
    assert client.get("/referrals/worklist").status_code == 200
    rows = _rows(db)
    assert len(rows) == 3
    assert all(r.referral_id is not None and r.patient_id is not None for r in rows)
    lines = _audit_lines(caplog, "referral.list")
    assert len(lines) == 1
    assert lines[0]["referral_ids"] == sorted([r1.id, r2.id, r3.id])
    assert lines[0]["patient_ids"] == sorted([patient.id, other.id])


def test_empty_worklist_logs_but_writes_no_rows(client, db, caplog):
    caplog.set_level(logging.INFO, logger="careroute.audit")
    assert client.get("/referrals/worklist").status_code == 200
    assert _rows(db) == []
    lines = _audit_lines(caplog, "referral.list")
    assert len(lines) == 1
    assert lines[0]["referral_ids"] == [] and lines[0]["patient_ids"] == []


def test_worklist_limit_bounds(client, db, submitted_referral):
    assert client.get("/referrals/worklist?limit=0").status_code == 422
    assert client.get("/referrals/worklist?limit=101").status_code == 422
    assert _rows(db) == []
    assert client.get("/referrals/worklist?limit=100").status_code == 200


def test_viewer_read_is_recorded(client_as, db, submitted_referral):
    viewer = client_as(UserRole.VIEWER)
    assert viewer.get(f"/referrals/{submitted_referral.id}").status_code == 200
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0].actor == "viewer@test.careroute"


def test_patient_create_row_has_patient_only(client, db):
    resp = client.post(
        "/patients",
        json={"mrn": "MRN-P-1", "full_name": "P One", "date_of_birth": "2001-01-01"},
    )
    assert resp.status_code == 201
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0].action == "patient.create"
    assert rows[0].referral_id is None
    assert rows[0].patient_id == resp.json()["id"]


def test_assign_records_old_and_new_provider(
    client, db, facility, provider, submitted_referral, caplog
):
    caplog.set_level(logging.INFO, logger="careroute.audit")
    second = Provider(
        facility_id=facility.id,
        npi="2234567890",
        full_name="Dr. Second",
        specialty="Cardiology",
        accepting_new_patients=True,
    )
    db.add(second)
    db.commit()
    url = f"/referrals/{submitted_referral.id}/assign"
    assert client.post(url, json={"provider_id": provider.id}).status_code == 200
    assert client.post(url, json={"provider_id": second.id}).status_code == 200
    rows = _rows(db)
    assert len(rows) == 2
    assert rows[0].old_provider_id is None and rows[0].new_provider_id == provider.id
    assert rows[1].old_provider_id == provider.id
    assert rows[1].new_provider_id == second.id
    lines = _audit_lines(caplog, "referral.assign")
    assert [(ln["old_provider_id"], ln["new_provider_id"]) for ln in lines] == [
        (None, provider.id),
        (provider.id, second.id),
    ]


def test_failures_write_no_rows(
    client, client_as, anon_client, db, facility, patient, submitted_referral, caplog
):
    caplog.set_level(logging.INFO, logger="careroute.audit")
    derm = Provider(
        facility_id=facility.id,
        npi="3334567890",
        full_name="Dr. Derm",
        specialty="Dermatology",
        accepting_new_patients=True,
    )
    db.add(derm)
    db.commit()
    body = {"mrn": patient.mrn, "full_name": "Dup", "date_of_birth": "2000-01-01"}
    assert client.get("/referrals/999999").status_code == 404
    assert client_as(UserRole.VIEWER).post("/patients", json=body).status_code == 403
    assert client.post("/patients", json=body).status_code == 409
    resp = client.post(
        f"/referrals/{submitted_referral.id}/assign", json={"provider_id": derm.id}
    )
    assert resp.status_code == 409
    assert anon_client.get("/referrals/worklist").status_code == 401
    assert _rows(db) == []
    new = [ln for ln in _audit_lines(caplog) if ln["action"] in access_audit.ACTIONS]
    assert new == []


def test_actor_cannot_be_spoofed(client, db, patient, facility):
    resp = client.post(
        "/referrals?actor=attacker@evil.example",
        json={
            "patient_id": patient.id,
            "origin_facility_id": facility.id,
            "specialty_requested": "Cardiology",
            "actor": "attacker@evil.example",
        },
        headers={"X-Actor": "attacker@evil.example"},
    )
    assert resp.status_code == 201
    rows = _rows(db)
    assert rows and all(r.actor == COORD for r in rows)


def test_audit_lines_carry_no_phi(client, facility, caplog):
    caplog.set_level(logging.INFO, logger="careroute.audit")
    p = client.post(
        "/patients",
        json={
            "mrn": "MRN-SENTINEL-9",
            "full_name": "Sentinel Phiname",
            "date_of_birth": "1911-11-11",
        },
    ).json()
    ref = client.post(
        "/referrals",
        json={
            "patient_id": p["id"],
            "origin_facility_id": facility.id,
            "specialty_requested": "Cardiology",
            "reason": "sentinel reason text",
        },
    ).json()
    client.post(f"/referrals/{ref['id']}/status", json={"to_status": "submitted"})
    client.post(
        f"/referrals/{ref['id']}/status",
        json={"to_status": "accepted", "note": "sentinel note text"},
    )
    client.get("/referrals/worklist")
    client.get(f"/referrals/{ref['id']}")
    lines = _audit_lines(caplog)
    assert lines
    blob = json.dumps(lines).lower()
    for s in (
        "sentinel",
        "phiname",
        "mrn-sentinel-9",
        "1911-11-11",
    ):
        assert s not in blob


def _boom(*args, **kwargs):
    raise OperationalError("audit", None, Exception("down"))


def _token_client(make_user):
    token = create_access_token(make_user(UserRole.COORDINATOR))
    return TestClient(
        app,
        raise_server_exceptions=False,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_fail_closed_read(make_user, submitted_referral, monkeypatch):
    monkeypatch.setattr(access_audit, "stage", _boom)
    resp = _token_client(make_user).get(f"/referrals/{submitted_referral.id}")
    assert resp.status_code == 500
    assert "Cardiology" not in resp.text
    assert "patient_id" not in resp.text


def test_fail_closed_write_rolls_back(make_user, db, submitted_referral, monkeypatch):
    monkeypatch.setattr(access_audit, "stage", _boom)
    resp = _token_client(make_user).post(
        f"/referrals/{submitted_referral.id}/status", json={"to_status": "accepted"}
    )
    assert resp.status_code == 500
    db.expire_all()
    assert db.get(Referral, submitted_referral.id).status == ReferralStatus.SUBMITTED
    assert _rows(db) == []


def test_fail_closed_on_real_permission_error(make_user, submitted_referral):
    from tests.conftest import owner_engine

    role = os.environ.get("APP_DB_ROLE", "careroute_app")
    with owner_engine.begin() as conn:
        conn.execute(text(f'REVOKE INSERT ON record_access FROM "{role}"'))
    try:
        resp = _token_client(make_user).get("/referrals/worklist")
        assert resp.status_code == 500
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text(f'GRANT INSERT ON record_access TO "{role}"'))
