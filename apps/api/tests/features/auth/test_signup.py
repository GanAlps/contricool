"""Tests for ``POST /v1/auth/signup``."""
from __future__ import annotations

from fastapi.testclient import TestClient

_VALID = {
    "email": "alice@example.com",
    "password": "P@ssword123!",
    "name": "Alice",
    "currency": "USD",
}


def test_signup_happy_path_returns_202(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    r = auth_client.post("/v1/auth/signup", json=_VALID)
    assert r.status_code == 202
    body = r.json()
    assert len(body["user_id"]) == 26
    assert body["status"] == "PENDING_VERIFICATION"


def test_signup_with_phone_stores_phone_attribute(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    r = auth_client.post(
        "/v1/auth/signup", json={**_VALID, "phone": "+15551234567"}
    )
    assert r.status_code == 202


def test_signup_invalid_email_422(auth_client: TestClient) -> None:
    r = auth_client.post("/v1/auth/signup", json={**_VALID, "email": "not-an-email"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    fields = [d["field"] for d in r.json()["error"]["details"]]
    assert "email" in fields


def test_signup_invalid_phone_422(auth_client: TestClient) -> None:
    r = auth_client.post(
        "/v1/auth/signup", json={**_VALID, "phone": "555-1234"}
    )
    assert r.status_code == 422
    fields = [d["field"] for d in r.json()["error"]["details"]]
    assert "phone" in fields


def test_signup_unknown_currency_422(auth_client: TestClient) -> None:
    r = auth_client.post("/v1/auth/signup", json={**_VALID, "currency": "EUR"})
    assert r.status_code == 422


def test_signup_short_password_422(auth_client: TestClient) -> None:
    r = auth_client.post("/v1/auth/signup", json={**_VALID, "password": "shrt"})
    assert r.status_code == 422


def test_signup_weak_password_rejected_by_cognito(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Cognito's complexity policy fires when length passes but
    upper/lower/digit/symbol are missing."""
    r = auth_client.post(
        "/v1/auth/signup", json={**_VALID, "password": "lowercaseonly"}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_PASSWORD"


def test_signup_duplicate_email_409(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    auth_client.post("/v1/auth/signup", json=_VALID)
    r = auth_client.post("/v1/auth/signup", json=_VALID)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EMAIL_EXISTS"


def test_signup_extra_field_rejected(auth_client: TestClient) -> None:
    """``extra="forbid"`` rejects typo'd / attacker-added fields."""
    r = auth_client.post(
        "/v1/auth/signup", json={**_VALID, "is_admin": True}
    )
    assert r.status_code == 422


def test_signup_writes_pending_currency_row(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Phase 2c writes EMAIL#<hash>#PENDING with the chosen currency,
    so that verify-email can copy it into the META row."""
    from app.core.lookup_hash import email_hash

    auth_client.post("/v1/auth/signup", json={**_VALID, "currency": "INR"})
    table = auth_env["table"]
    item = table.get_item(  # type: ignore[attr-defined]
        Key={"PK": f"EMAIL#{email_hash(_VALID['email'])}", "SK": "PENDING"}
    ).get("Item")
    assert item is not None
    assert item["currency"] == "INR"
