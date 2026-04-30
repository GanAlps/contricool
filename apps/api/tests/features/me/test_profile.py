"""``PATCH /v1/me/profile`` integration tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.features.transactions.conftest import (
    auth_headers_for,
    seed_user,
)

A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"


def test_update_profile_changes_name(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="Alice")
    r = txn_client.patch(
        "/v1/me/profile",
        json={"name": "Alicia"},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"user_id": A, "name": "Alicia", "currency": "USD"}

    # META row reflects the new name (stored as display_name on disk).
    item = txn_env["users_table"].get_item(  # type: ignore[attr-defined]
        Key={"PK": f"USER#{A}", "SK": "META"}
    ).get("Item")
    assert item is not None
    assert item.get("display_name") == "Alicia"


def test_update_profile_trims_whitespace(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="Alice")
    r = txn_client.patch(
        "/v1/me/profile",
        json={"name": "  Alicia  "},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Alicia"


def test_update_profile_blank_name_returns_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="Alice")
    r = txn_client.patch(
        "/v1/me/profile",
        json={"name": "   "},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_update_profile_empty_name_pydantic_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="Alice")
    r = txn_client.patch(
        "/v1/me/profile",
        json={"name": ""},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 422


def test_update_profile_extra_fields_rejected(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """email + currency must NOT be settable through this endpoint."""
    seed_user(txn_env, user_id=A, email="a@x.com", name="Alice")
    r = txn_client.patch(
        "/v1/me/profile",
        json={"name": "A", "currency": "INR"},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 422
    r = txn_client.patch(
        "/v1/me/profile",
        json={"name": "A", "email": "evil@example.com"},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 422


def test_update_profile_unauthenticated_returns_401(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    r = txn_client.patch("/v1/me/profile", json={"name": "X"})
    assert r.status_code == 401


def test_update_profile_deactivated_user_403(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="Alice")
    txn_env["users_table"].update_item(  # type: ignore[attr-defined]
        Key={"PK": f"USER#{A}", "SK": "META"},
        UpdateExpression="SET #s = :d",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":d": "deactivated"},
    )
    r = txn_client.patch(
        "/v1/me/profile",
        json={"name": "Alicia"},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "NOT_ALLOWED"


def test_update_profile_same_name_succeeds(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Idempotent: setting the current name still returns 200."""
    seed_user(txn_env, user_id=A, email="a@x.com", name="Alice")
    r = txn_client.patch(
        "/v1/me/profile",
        json={"name": "Alice"},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Alice"
