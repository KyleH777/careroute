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
