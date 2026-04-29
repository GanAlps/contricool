"""Tests for the liveness endpoint."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import AppConfig
from app.core.middleware import install_core_middleware


@pytest.fixture
def health_client(
    seed_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Build a fresh app per test so ``ENV_NAME`` overrides take effect.

    The route reads ``ENV_NAME`` and ``APP_VERSION`` from process env
    rather than ``AppConfig`` (it pre-dates Phase 2b). Keep that contract
    for now — Phase 2c may unify it.
    """
    monkeypatch.setenv("ENV_NAME", "test-env")
    monkeypatch.setenv("APP_VERSION", "1.2.3")

    from app.routes import health

    api = FastAPI()
    install_core_middleware(api)
    api.include_router(health.router, prefix="/v1", tags=["health"])
    with TestClient(api) as c:
        yield c


def test_health_returns_ok_with_env_and_version(health_client: TestClient) -> None:
    response = health_client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "env": "test-env", "version": "1.2.3"}


def test_health_defaults_when_env_unset(
    seed_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ENV_NAME", raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)

    from app.routes import health

    api = FastAPI()
    install_core_middleware(api)
    api.include_router(health.router, prefix="/v1", tags=["health"])
    with TestClient(api) as c:
        response = c.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] == "unknown"
    assert body["version"] == "0.0.1"


def test_health_requires_no_auth(health_client: TestClient) -> None:
    """Liveness must be unauthenticated — exempt from the API Gateway JWT authorizer."""
    response = health_client.get("/v1/health")  # no Authorization header
    assert response.status_code == 200


def test_health_response_carries_request_id(health_client: TestClient) -> None:
    """Regression: CoreMiddleware echoes X-Request-Id on every response."""
    response = health_client.get("/v1/health")
    assert response.headers.get("X-Request-Id"), (
        "CoreMiddleware must populate X-Request-Id even on /v1/health."
    )
