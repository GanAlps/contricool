"""``GET /v1/transactions/{txn_id}`` tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import auth_headers_for, seed_friendship, seed_user

A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
B = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"
C = "01HK3W7QF6VMYG8XR3DQ7B5N6R"
D = "01HK3W7QF6VMYG8XR3DQ7B5N6S"


def _create_dinner(
    client: TestClient, env: dict[str, object], *, key: str = "k1"
) -> str:
    seed_user(env, user_id=A, email="a@x.com", name="A")
    seed_user(env, user_id=B, email="b@x.com", name="B")
    seed_user(env, user_id=C, email="c@x.com", name="C")
    seed_friendship(env, a_id=A, b_id=B)
    seed_friendship(env, a_id=A, b_id=C)
    body = {
        "name": "Dinner",
        "type": "expense",
        "amount": "30.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}, {"user_id": C}],
        "payers": [{"user_id": A, "paid_amount": "30.00"}],
    }
    resp = client.post(
        "/v1/transactions",
        json=body,
        headers={**auth_headers_for(A), "Idempotency-Key": key},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["txn_id"]  # type: ignore[no-any-return]


def test_get_as_member_returns_full_shape(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    txn_id = _create_dinner(txn_client, txn_env)
    resp = txn_client.get(
        f"/v1/transactions/{txn_id}", headers=auth_headers_for(B, "b@x.com")
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["txn_id"] == txn_id
    assert {m["user_id"] for m in body["members"]} == {A, B, C}


def test_get_as_non_member_returns_404_mask(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    txn_id = _create_dinner(txn_client, txn_env, key="k-nonmember")
    seed_user(txn_env, user_id=D, email="d@x.com", name="D")
    resp = txn_client.get(
        f"/v1/transactions/{txn_id}", headers=auth_headers_for(D, "d@x.com")
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_get_invalid_ulid_path_rejects_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    resp = txn_client.get(
        "/v1/transactions/not-a-ulid", headers=auth_headers_for(A)
    )
    assert resp.status_code == 422


def test_get_unknown_txn_returns_404(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    resp = txn_client.get(
        f"/v1/transactions/{A}",  # ULID-shaped but doesn't exist
        headers=auth_headers_for(A),
    )
    assert resp.status_code == 404


def test_get_without_jwt_rejects_401(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    resp = txn_client.get(f"/v1/transactions/{A}")
    assert resp.status_code == 401
