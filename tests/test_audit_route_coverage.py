"""Route-enumeration guard: every route is audited or explicitly exempt (ADR-0014)."""

from fastapi.routing import APIRoute

from app import access_audit
from app.main import app
from tests import test_access_audit

EXEMPT = {
    ("GET", "/health"),  # liveness probe, no data
    ("GET", "/ready"),  # readiness probe, no data
    ("GET", "/stats"),  # aggregate row counts only, no records
    ("POST", "/auth/token"),  # login; returns a token, logged by login_attempts
    ("GET", "/auth/me"),  # caller's own staff account, not patient data
}


def _routes():
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.endpoint.__module__.startswith("tests."):
            continue  # routes registered by tests (e.g. /_boom_for_test)
        for method in sorted(route.methods - {"HEAD"}):
            yield method, route.path, getattr(route.endpoint, "__audit_action__", None)


def test_every_route_is_audited_or_exempt():
    for method, path, action in _routes():
        assert action or (method, path) in EXEMPT, (
            f"{method} {path} is neither audited nor exempt: add "
            "@access_audit.audited(...) or an EXEMPT entry"
        )


def test_exempt_has_no_stale_entries():
    existing = {(m, p) for m, p, _ in _routes()}
    assert EXEMPT <= existing


def test_declared_actions_are_known():
    for _m, _p, action in _routes():
        assert action is None or action in access_audit.ACTIONS


def test_behaviour_table_covers_every_audited_route():
    marked = {(m, p): a for m, p, a in _routes() if a}
    assert set(marked) == set(test_access_audit.BEHAVIOUR)
    for key, action in marked.items():
        assert test_access_audit.BEHAVIOUR[key][0] == action
