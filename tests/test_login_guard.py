"""Login rate limiting and the login-attempt log (LOGIN-01/02, ADR-0013)."""

import json
import logging

import pytest
from sqlalchemy import text

from app.config import settings
from app.models import LoginAttempt, LoginOutcome, UserRole
from tests.conftest import TEST_PASSWORD, owner_engine

WRONG = "definitely-not-the-password"


@pytest.fixture()
def behind_proxy(monkeypatch):
    """Simulate Container Apps ingress: trust one hop of X-Forwarded-For."""
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)


def _login(client, email, password, ip=None, xff=None):
    headers = {}
    if xff is not None:
        headers["X-Forwarded-For"] = xff
    elif ip is not None:
        headers["X-Forwarded-For"] = ip
    return client.post(
        "/auth/token", data={"username": email, "password": password}, headers=headers
    )


def _attempts(db):
    db.expire_all()
    return db.query(LoginAttempt).order_by(LoginAttempt.id).all()


def _age_all_attempts(seconds):
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "update login_attempts set occurred_at = occurred_at - make_interval(secs => :s)"
            ),
            {"s": seconds},
        )


# --- per-email limit ---------------------------------------------------------


def test_sixth_failure_for_one_email_is_429_with_retry_after(anon_client, make_user):
    user = make_user(UserRole.VIEWER)
    for _ in range(settings.login_max_failures_per_email):
        assert _login(anon_client, user.email, WRONG).status_code == 401

    blocked = _login(anon_client, user.email, TEST_PASSWORD)
    assert blocked.status_code == 429
    retry = int(blocked.headers["Retry-After"])
    assert 1 <= retry <= settings.login_window_seconds
    assert blocked.json() == {"detail": "too many login attempts; try again later"}


def test_limit_lifts_after_the_window(anon_client, make_user):
    user = make_user(UserRole.VIEWER)
    for _ in range(settings.login_max_failures_per_email):
        _login(anon_client, user.email, WRONG)
    assert _login(anon_client, user.email, TEST_PASSWORD).status_code == 429

    _age_all_attempts(settings.login_window_seconds + 1)
    assert _login(anon_client, user.email, TEST_PASSWORD).status_code == 200


def test_successes_do_not_count_toward_the_limit(anon_client, make_user):
    user = make_user(UserRole.VIEWER)
    for _ in range(settings.login_max_failures_per_email + 3):
        assert _login(anon_client, user.email, TEST_PASSWORD).status_code == 200


def test_email_limit_is_case_insensitive(anon_client, make_user):
    user = make_user(UserRole.VIEWER)
    for i in range(settings.login_max_failures_per_email):
        email = user.email.upper() if i % 2 else user.email
        _login(anon_client, email, WRONG)
    assert _login(anon_client, user.email, TEST_PASSWORD).status_code == 429


def test_429_is_identical_for_known_and_unknown_emails(anon_client, make_user):
    user = make_user(UserRole.VIEWER)
    unknown = "nobody-at-all@test.careroute"
    for _ in range(settings.login_max_failures_per_email):
        _login(anon_client, user.email, WRONG)
        _login(anon_client, unknown, WRONG)
    known = _login(anon_client, user.email, WRONG)
    ghost = _login(anon_client, unknown, WRONG)
    assert known.status_code == ghost.status_code == 429
    assert known.json() == ghost.json()
    assert set(known.headers) - {
        "x-request-id",
        "retry-after",
        "content-length",
    } == set(ghost.headers) - {"x-request-id", "retry-after", "content-length"}


# --- per-IP limit ------------------------------------------------------------


def test_one_ip_many_emails_hits_the_ip_limit(anon_client, behind_proxy):
    for i in range(settings.login_max_failures_per_ip):
        r = _login(anon_client, f"spray{i}@test.careroute", WRONG, ip="198.51.100.9")
        assert r.status_code == 401
    r = _login(anon_client, "fresh@test.careroute", WRONG, ip="198.51.100.9")
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    # A different IP is unaffected.
    r = _login(anon_client, "fresh@test.careroute", WRONG, ip="198.51.100.10")
    assert r.status_code == 401


def test_forged_leading_xff_entries_are_ignored(anon_client, behind_proxy, db):
    # Envoy appends the real peer; the client controls everything left of it.
    for i in range(settings.login_max_failures_per_ip):
        _login(
            anon_client,
            f"forge{i}@test.careroute",
            WRONG,
            xff=f"203.0.113.{i}, 198.51.100.77",
        )
    r = _login(
        anon_client, "x@test.careroute", WRONG, xff="203.0.113.250, 198.51.100.77"
    )
    assert r.status_code == 429
    ips = {str(a.client_ip) for a in _attempts(db)}
    assert ips == {"198.51.100.77"}


def test_malformed_xff_falls_back_to_socket_peer(anon_client, behind_proxy, db):
    _login(anon_client, "a@test.careroute", WRONG, xff="not-an-ip")
    # The TestClient's peer ("testclient") isn't an IP either, so nothing is
    # stored rather than something invented.
    assert _attempts(db)[-1].client_ip is None


def test_without_trusted_hops_xff_is_ignored(anon_client, db):
    _login(anon_client, "a@test.careroute", WRONG, xff="198.51.100.5")
    assert _attempts(db)[-1].client_ip is None


# --- the attempt log -----------------------------------------------------------


def test_every_attempt_is_recorded_without_the_password(
    anon_client, make_user, behind_proxy, db, caplog
):
    caplog.set_level(logging.INFO)
    user = make_user(UserRole.VIEWER)
    ok = _login(anon_client, user.email.upper(), TEST_PASSWORD, ip="198.51.100.1")
    bad = _login(anon_client, user.email, WRONG, ip="198.51.100.1")
    for _ in range(settings.login_max_failures_per_email):
        _login(anon_client, user.email, WRONG, ip="198.51.100.1")
    limited = _login(anon_client, user.email, WRONG, ip="198.51.100.1")

    rows = _attempts(db)
    assert [r.outcome for r in rows[:2]] == [LoginOutcome.SUCCESS, LoginOutcome.FAILURE]
    assert rows[-1].outcome == LoginOutcome.RATE_LIMITED
    assert all(r.email == user.email for r in rows)
    assert str(rows[0].client_ip) == "198.51.100.1"
    assert rows[0].occurred_at is not None
    assert rows[0].request_id == ok.headers["X-Request-ID"]
    assert rows[1].request_id == bad.headers["X-Request-ID"]
    assert rows[-1].request_id == limited.headers["X-Request-ID"]

    for r in rows:
        values = " ".join(
            str(getattr(r, c.key)) for c in LoginAttempt.__table__.columns
        )
        assert TEST_PASSWORD not in values and WRONG not in values
    for rec in caplog.records:
        assert TEST_PASSWORD not in rec.getMessage() and WRONG not in rec.getMessage()
        assert TEST_PASSWORD not in json.dumps(getattr(rec, "fields", {}), default=str)


def test_attempts_emit_audit_lines(anon_client, make_user, caplog):
    caplog.set_level(logging.INFO, logger="careroute.audit")
    user = make_user(UserRole.VIEWER)
    _login(anon_client, user.email, TEST_PASSWORD)
    _login(anon_client, user.email, WRONG)
    lines = [
        r.fields
        for r in caplog.records
        if r.name == "careroute.audit" and r.fields.get("action") == "auth.login"
    ]
    assert [line["outcome"] for line in lines] == ["success", "failure"]
    assert all(line["email"] == user.email for line in lines)
