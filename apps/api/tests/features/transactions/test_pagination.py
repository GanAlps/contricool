"""Pagination cursor tests for ``GET /v1/transactions``."""
from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import auth_headers_for, seed_friendship, seed_user

A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
B = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"


def _seed(env: dict[str, object]) -> None:
    seed_user(env, user_id=A, email="a@x.com", name="A")
    seed_user(env, user_id=B, email="b@x.com", name="B")
    seed_friendship(env, a_id=A, b_id=B)


def _post_eq(client: TestClient, *, key: str, name: str) -> None:
    body = {
        "name": name,
        "type": "expense",
        "amount": "10.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}],
        "payers": [{"user_id": A, "paid_amount": "10.00"}],
    }
    resp = client.post(
        "/v1/transactions",
        json=body,
        headers={**auth_headers_for(A), "Idempotency-Key": key},
    )
    assert resp.status_code == 201, resp.text


def test_list_pagination_returns_cursor_and_next_page(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed(txn_env)
    for i in range(5):
        _post_eq(txn_client, key=f"page-key-{i}", name=f"Item {i}")
    # Limit=2 → first page returns 2 items + cursor.
    first = txn_client.get(
        "/v1/transactions?limit=2", headers=auth_headers_for(A)
    )
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None

    # Second page using the cursor.
    cursor = body["next_cursor"]
    second = txn_client.get(
        f"/v1/transactions?limit=2&cursor={cursor}", headers=auth_headers_for(A)
    )
    assert second.status_code == 200
    body2 = second.json()
    assert len(body2["items"]) == 2
    # Distinct items.
    page1_ids = {item["txn_id"] for item in body["items"]}
    page2_ids = {item["txn_id"] for item in body2["items"]}
    assert page1_ids.isdisjoint(page2_ids)


def test_list_with_invalid_cursor_rejects_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed(txn_env)
    resp = txn_client.get(
        "/v1/transactions?cursor=not-a-real-cursor", headers=auth_headers_for(A)
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_CURSOR"
