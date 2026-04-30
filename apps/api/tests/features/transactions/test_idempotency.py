"""Idempotency tests for ``POST /v1/transactions``."""
from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import auth_headers_for, seed_friendship, seed_user

A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
B = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"
C = "01HK3W7QF6VMYG8XR3DQ7B5N6R"


def _seed(env: dict[str, object]) -> None:
    for uid, email in [(A, "a@x.com"), (B, "b@x.com"), (C, "c@x.com")]:
        seed_user(env, user_id=uid, email=email, name=email[0].upper())
    seed_friendship(env, a_id=A, b_id=B)
    seed_friendship(env, a_id=A, b_id=C)
    seed_friendship(env, a_id=B, b_id=C)


def _body() -> dict[str, object]:
    return {
        "name": "Dinner",
        "type": "expense",
        "amount": "30.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}, {"user_id": C}],
        "payers": [{"user_id": A, "paid_amount": "30.00"}],
    }


def test_replay_with_same_key_and_body_returns_cached_response(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed(txn_env)
    headers = {**auth_headers_for(A), "Idempotency-Key": "shared-key"}
    first = txn_client.post("/v1/transactions", json=_body(), headers=headers)
    assert first.status_code == 201
    txn_id = first.json()["txn_id"]
    second = txn_client.post("/v1/transactions", json=_body(), headers=headers)
    assert second.status_code == 201
    assert second.json()["txn_id"] == txn_id


def test_same_key_different_body_returns_409_reused(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed(txn_env)
    headers = {**auth_headers_for(A), "Idempotency-Key": "reused-key"}
    first = txn_client.post("/v1/transactions", json=_body(), headers=headers)
    assert first.status_code == 201
    different = _body() | {"name": "Different"}
    second = txn_client.post(
        "/v1/transactions", json=different, headers=headers
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_different_users_same_key_independent(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed(txn_env)
    a_headers = {**auth_headers_for(A), "Idempotency-Key": "shared-across-users"}
    b_headers = {**auth_headers_for(B, "b@x.com"), "Idempotency-Key": "shared-across-users"}
    a_resp = txn_client.post("/v1/transactions", json=_body(), headers=a_headers)
    b_resp = txn_client.post("/v1/transactions", json=_body(), headers=b_headers)
    assert a_resp.status_code == 201
    assert b_resp.status_code == 201
    assert a_resp.json()["txn_id"] != b_resp.json()["txn_id"]
