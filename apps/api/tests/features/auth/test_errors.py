"""Tests for ``app.features.auth.errors`` envelope + handlers."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.config import AppConfig
from app.core.dependencies import UnauthenticatedError
from app.core.middleware import install_core_middleware
from app.features.auth.errors import AuthError, install_error_handlers


class _Body(BaseModel):
    email: str = Field(min_length=3)
    currency: str


@pytest.fixture
def envelope_app(seed_config: AppConfig) -> FastAPI:
    api = FastAPI()
    install_core_middleware(api)
    install_error_handlers(api)

    @api.get("/raise-auth")
    async def _raise_auth() -> None:
        raise AuthError(
            code="EMAIL_EXISTS",
            http_status=409,
            message="An account with this email already exists.",
        )

    @api.get("/raise-rate")
    async def _raise_rate() -> None:
        raise AuthError(
            code="RATE_LIMITED",
            http_status=429,
            message="Too many attempts.",
            retry_after_seconds=42,
        )

    @api.get("/raise-detail")
    async def _raise_detail() -> None:
        raise AuthError(
            code="INVALID_PASSWORD",
            http_status=422,
            message="Password does not meet requirements.",
            details=[{"field": "password", "issue": "too short"}],
        )

    @api.get("/raise-unauth")
    async def _raise_unauth() -> None:
        raise UnauthenticatedError("missing header")

    @api.get("/raise-unhandled")
    async def _raise_unhandled() -> None:
        raise RuntimeError("synthetic boom")

    @api.post("/validate")
    async def _validate(body: _Body) -> dict[str, str]:
        return {"ok": "yes", "email": body.email, "currency": body.currency}

    async def _dep() -> None:
        raise UnauthenticatedError("dep failed")

    @api.get("/raise-unauth-via-dep")
    async def _via_dep(_: None = Depends(_dep)) -> None:
        return None

    return api


@pytest.fixture
def envelope_client(envelope_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(envelope_app, raise_server_exceptions=False) as c:
        yield c


def test_auth_error_envelope_shape(envelope_client: TestClient) -> None:
    r = envelope_client.get("/raise-auth")
    assert r.status_code == 409
    body = r.json()
    assert body["error"]["code"] == "EMAIL_EXISTS"
    assert body["error"]["message"] == "An account with this email already exists."
    assert "request_id" in body["error"]
    assert body["error"]["request_id"]  # populated by CoreMiddleware


def test_retry_after_header_set_on_rate_limit(envelope_client: TestClient) -> None:
    r = envelope_client.get("/raise-rate")
    assert r.status_code == 429
    assert r.headers.get("Retry-After") == "42"
    assert r.json()["error"]["code"] == "RATE_LIMITED"


def test_details_passed_through(envelope_client: TestClient) -> None:
    r = envelope_client.get("/raise-detail")
    assert r.status_code == 422
    assert r.json()["error"]["details"] == [
        {"field": "password", "issue": "too short"}
    ]


def test_unauthenticated_error_via_handler(envelope_client: TestClient) -> None:
    r = envelope_client.get("/raise-unauth")
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["error"]["message"] == "Authentication required."
    # No Retry-After header on plain 401.
    assert "Retry-After" not in r.headers


def test_unauthenticated_via_dependency(envelope_client: TestClient) -> None:
    r = envelope_client.get("/raise-unauth-via-dep")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_unhandled_exception_returns_500(envelope_client: TestClient) -> None:
    r = envelope_client.get("/raise-unhandled")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "INTERNAL"
    assert body["error"]["message"] == "An internal error occurred."
    # The synthetic exception message must NOT leak into the response.
    assert "synthetic boom" not in r.text


def test_validation_error_drops_body_prefix(envelope_client: TestClient) -> None:
    r = envelope_client.post("/validate", json={"email": "x"})
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    fields = [d["field"] for d in body["error"]["details"]]
    # Field paths drop the "body" prefix Pydantic emits.
    assert "email" in fields
    assert "currency" in fields
    assert all(not f.startswith("body.") for f in fields)


def test_request_id_is_unknown_when_state_missing(envelope_client: TestClient) -> None:
    """When middleware didn't run (synthetic case), envelope still has ``request_id``."""
    # Build a one-off app without CoreMiddleware so request.state is empty.
    api = FastAPI()
    install_error_handlers(api)

    @api.get("/raise")
    async def _raise() -> None:
        raise AuthError(code="X", http_status=400, message="x")

    with TestClient(api, raise_server_exceptions=False) as c:
        r = c.get("/raise")
    assert r.status_code == 400
    assert r.json()["error"]["request_id"] == "unknown"
