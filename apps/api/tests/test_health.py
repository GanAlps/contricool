"""Tests for the liveness endpoint."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok_with_env_and_version(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ENV_NAME", "test")
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    client = TestClient(app)

    response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "env": "test", "version": "1.2.3"}


def test_health_defaults_when_env_unset(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("ENV_NAME", raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)
    client = TestClient(app)

    response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] == "unknown"
    assert body["version"] == "0.0.1"


def test_health_requires_no_auth() -> None:
    """Liveness must be unauthenticated — exempt from the API Gateway JWT authorizer."""
    client = TestClient(app)
    response = client.get("/v1/health")  # no Authorization header
    assert response.status_code == 200
