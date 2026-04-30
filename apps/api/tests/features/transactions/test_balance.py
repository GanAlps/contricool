"""End-to-end balance tests via ``GET /v1/friends/{id}/balance``.

The route lives in the friends feature but the math is the
transactions feature's :func:`service.compute_pair_balance`. We
exercise it through the public route here.
"""
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


def _create_dinner(client: TestClient, *, key: str = "k") -> None:
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


def test_balance_after_dinner_a_owes_received(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed(txn_env)
    _create_dinner(txn_client, key="balance1")
    # A's balance with B → B owes A 10.
    resp = txn_client.get(
        f"/v1/friends/{B}/balance", headers=auth_headers_for(A)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["net"] == "10.00"
    assert body["settlement_status"] == "friend_owes"


def test_balance_b_perspective_is_negative(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed(txn_env)
    _create_dinner(txn_client, key="balance2")
    resp = txn_client.get(
        f"/v1/friends/{A}/balance", headers=auth_headers_for(B, "b@x.com")
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["net"] == "-10.00"
    assert body["settlement_status"] == "you_owe"


def test_settlement_zeros_balance(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed(txn_env)
    _create_dinner(txn_client, key="balance3-dinner")
    # B settles their $10 share.
    settle_body = {
        "name": "Settling up",
        "type": "settlement",
        "amount": "10.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "amount",
        "members": [
            {"user_id": A, "owed_amount": "10.00"},
            {"user_id": B, "owed_amount": "0.00"},
        ],
        "payers": [{"user_id": B, "paid_amount": "10.00"}],
    }
    resp = txn_client.post(
        "/v1/transactions",
        json=settle_body,
        headers={**auth_headers_for(B, "b@x.com"), "Idempotency-Key": "balance3-settle"},
    )
    assert resp.status_code == 201, resp.text
    resp = txn_client.get(
        f"/v1/friends/{B}/balance", headers=auth_headers_for(A)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["net"] == "0.00"
    assert body["settlement_status"] == "settled"


def test_no_transactions_means_settled(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed(txn_env)
    resp = txn_client.get(
        f"/v1/friends/{B}/balance", headers=auth_headers_for(A)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["net"] == "0.00"
    assert body["settlement_status"] == "settled"
