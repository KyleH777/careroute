"""Smoke test: proves the pytest harness (Docker test stage + ephemeral
Postgres + migrations) actually works, before any feature code is added."""

from sqlalchemy.exc import OperationalError

from app.db import get_session
from app.main import app


def test_health_endpoint_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_is_503_when_database_unreachable(client):
    """An orchestrator reads the status code, so degraded must not be 2xx."""

    class _DeadSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    app.dependency_overrides[get_session] = lambda: _DeadSession()
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unreachable"}


def test_unreachable_database_fails_fast():
    """A stopped DB server must not hang requests (2026-09-28 drill: /ready
    took minutes to 503). 10.255.255.1 is non-routable, so the connect can
    only end by timing out."""
    import time

    import pytest
    from sqlalchemy import text

    from app.config import settings
    from app.db import make_engine

    dead = make_engine("postgresql+psycopg://x:y@10.255.255.1:5432/careroute")
    start = time.monotonic()
    with pytest.raises(OperationalError):
        with dead.connect() as conn:
            conn.execute(text("select 1"))
    assert time.monotonic() - start < settings.db_connect_timeout + 5
