"""Request IDs, structured access/audit logs and Prometheus metrics (OBS-01/02/04)."""

import json
import logging
import re
import uuid

from prometheus_client import generate_latest

from app import observability
from app.observability import JsonFormatter

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _records(caplog, logger_name):
    return [r for r in caplog.records if r.name == logger_name]


def _json(record):
    return json.loads(JsonFormatter().format(record))


def test_request_id_generated_when_absent(anon_client):
    response = anon_client.get("/health")
    assert UUID_RE.match(response.headers["X-Request-ID"])


def test_valid_inbound_request_id_is_echoed(anon_client):
    response = anon_client.get("/health", headers={"X-Request-ID": "trace-abc.123_x"})
    assert response.headers["X-Request-ID"] == "trace-abc.123_x"


def test_invalid_inbound_request_id_is_replaced(anon_client):
    for bad in ["short", "x" * 65, "has spaces here", "semi;colon-12345"]:
        response = anon_client.get("/health", headers={"X-Request-ID": bad})
        rid = response.headers["X-Request-ID"]
        assert rid != bad
        assert UUID_RE.match(rid)


def test_one_json_access_line_per_request(client, submitted_referral, caplog):
    caplog.set_level(logging.INFO, logger="careroute.access")
    response = client.get(f"/referrals/{submitted_referral.id}?unused=secret-ish")
    lines = [_json(r) for r in _records(caplog, "careroute.access")]
    assert len(lines) == 1
    line = lines[0]
    assert line["event"] == "request"
    assert line["request_id"] == response.headers["X-Request-ID"]
    assert line["method"] == "GET"
    assert line["route"] == "/referrals/{referral_id}"
    assert line["path"] == f"/referrals/{submitted_referral.id}"
    assert "?" not in line["path"] and "secret-ish" not in json.dumps(line)
    assert line["status"] == 200
    assert isinstance(line["duration_ms"], float)


def test_unmatched_route_is_labelled(anon_client, caplog):
    caplog.set_level(logging.INFO, logger="careroute.access")
    anon_client.get("/no/such/thing")
    line = _json(_records(caplog, "careroute.access")[-1])
    assert line["status"] == 404
    assert line["route"] == "unmatched"


def test_status_change_emits_audit_line(client, submitted_referral, caplog):
    caplog.set_level(logging.INFO, logger="careroute.audit")
    response = client.post(
        f"/referrals/{submitted_referral.id}/status",
        json={"to_status": "accepted", "note": "free text stays out of logs"},
    )
    assert response.status_code == 200
    lines = [
        ln
        for ln in (_json(r) for r in _records(caplog, "careroute.audit"))
        if ln["action"] == "referral.status_changed"
    ]
    assert [ln["action"] for ln in lines] == ["referral.status_changed"]
    audit = lines[0]
    assert audit["event"] == "audit"
    assert audit["action"] == "referral.status_changed"
    assert audit["actor"] == "coordinator@test.careroute"
    assert audit["referral_id"] == submitted_referral.id
    assert audit["from_status"] == "submitted"
    assert audit["to_status"] == "accepted"
    assert audit["request_id"] == response.headers["X-Request-ID"]
    assert "free text" not in json.dumps(audit)


def test_create_referral_emits_audit_line(client, patient, facility, caplog):
    caplog.set_level(logging.INFO, logger="careroute.audit")
    response = client.post(
        "/referrals",
        json={
            "patient_id": patient.id,
            "origin_facility_id": facility.id,
            "specialty_requested": "Cardiology",
            "priority": "routine",
            "reason": "chest pain",
        },
    )
    assert response.status_code == 201
    audit = next(
        ln
        for ln in (_json(r) for r in _records(caplog, "careroute.audit"))
        if ln["action"] == "referral.created"
    )
    assert audit["referral_id"] == response.json()["id"]
    assert audit["from_status"] is None
    assert audit["to_status"] == "draft"
    assert "chest pain" not in json.dumps(audit)


def test_metrics_not_served_by_api(anon_client):
    assert anon_client.get("/metrics").status_code == 404


def test_metrics_registry_has_request_and_pool_series(anon_client):
    anon_client.get("/health")
    text = generate_latest(observability.REGISTRY).decode()
    assert re.search(
        r'careroute_http_requests_total\{method="GET",route="/health",status="200"\} \d',
        text,
    )
    assert "careroute_http_request_duration_seconds_bucket" in text
    assert "careroute_db_pool_checked_out" in text
    assert "careroute_db_pool_size" in text


def test_unhandled_error_still_gets_request_id_and_json_log(anon_client, caplog):
    from app.main import app

    @app.get("/_boom_for_test")
    def boom():
        raise RuntimeError("kaboom")

    try:
        caplog.set_level(logging.INFO)
        rid = f"boom-{uuid.uuid4().hex[:8]}"
        response = anon_client.get("/_boom_for_test", headers={"X-Request-ID": rid})
        assert response.status_code == 500
        assert response.headers["X-Request-ID"] == rid
        access = _json(_records(caplog, "careroute.access")[-1])
        assert access["status"] == 500 and access["request_id"] == rid
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", "") != "/_boom_for_test"
        ]
