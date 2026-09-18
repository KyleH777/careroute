"""Smoke test: proves the pytest harness (Docker test stage + ephemeral
Postgres + migrations) actually works, before any feature code is added."""


def test_health_endpoint_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
