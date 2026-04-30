"""``POST /v1/transactions`` happy-path tests."""
from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from .conftest import auth_headers_for, seed_friendship, seed_user

A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
B = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"
C = "01HK3W7QF6VMYG8XR3DQ7B5N6R"


def _seed_three_friends(env: dict[str, object]) -> None:
    seed_user(env, user_id=A, email="a@x.com", name="A")
    seed_user(env, user_id=B, email="b@x.com", name="B")
    seed_user(env, user_id=C, email="c@x.com", name="C")
    seed_friendship(env, a_id=A, b_id=B)
    seed_friendship(env, a_id=A, b_id=C)
    seed_friendship(env, a_id=B, b_id=C)


def test_create_equal_split_three_members_creator_pays(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
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
    resp = txn_client.post(
        "/v1/transactions",
        json=body,
        headers={**auth_headers_for(A, "a@x.com"), "Idempotency-Key": "key-create-1"},
    )
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["creator_id"] == A
    assert out["amount"] == "30.00"
    assert out["split_method"] == "equal"
    owed = {m["user_id"]: Decimal(m["owed_amount"]) for m in out["members"]}
    assert sum(owed.values()) == Decimal("30.00")
    # Equal split with rounding remainder absorbed by last member.
    # Member order in response mirrors request order (A, B, C).


def test_create_amount_split_explicit_owed_amounts(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    body = {
        "name": "Groceries",
        "type": "expense",
        "amount": "50.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "amount",
        "members": [
            {"user_id": A, "owed_amount": "20.00"},
            {"user_id": B, "owed_amount": "20.00"},
            {"user_id": C, "owed_amount": "10.00"},
        ],
        "payers": [{"user_id": A, "paid_amount": "50.00"}],
    }
    resp = txn_client.post(
        "/v1/transactions",
        json=body,
        headers={**auth_headers_for(A), "Idempotency-Key": "key-create-2"},
    )
    assert resp.status_code == 201, resp.text


def test_create_share_split_two_to_one(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    body = {
        "name": "Cab",
        "type": "expense",
        "amount": "30.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "share",
        "members": [
            {"user_id": A, "share": "1"},
            {"user_id": B, "share": "2"},
            {"user_id": C, "share": "1"},
        ],
        "payers": [{"user_id": A, "paid_amount": "30.00"}],
    }
    resp = txn_client.post(
        "/v1/transactions",
        json=body,
        headers={**auth_headers_for(A), "Idempotency-Key": "key-create-3"},
    )
    assert resp.status_code == 201, resp.text
    out = resp.json()
    owed = {m["user_id"]: Decimal(m["owed_amount"]) for m in out["members"]}
    # Shares are 1:2:1 so owed should be 7.50, 15.00, 7.50.
    assert owed[A] == Decimal("7.50")
    assert owed[B] == Decimal("15.00")
    assert owed[C] == Decimal("7.50")


def test_create_percent_split_clean(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    body = {
        "name": "Hotel",
        "type": "expense",
        "amount": "200.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "percent",
        "members": [
            {"user_id": A, "percent": "25"},
            {"user_id": B, "percent": "25"},
            {"user_id": C, "percent": "50"},
        ],
        "payers": [{"user_id": A, "paid_amount": "200.00"}],
    }
    resp = txn_client.post(
        "/v1/transactions",
        json=body,
        headers={**auth_headers_for(A), "Idempotency-Key": "key-create-4"},
    )
    assert resp.status_code == 201, resp.text


def test_create_settlement_two_members_one_payer(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    body = {
        "name": "Settling up",
        "type": "settlement",
        "amount": "10.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "amount",
        "members": [
            {"user_id": A, "owed_amount": "0.00"},
            {"user_id": B, "owed_amount": "10.00"},
        ],
        "payers": [{"user_id": A, "paid_amount": "10.00"}],
    }
    resp = txn_client.post(
        "/v1/transactions",
        json=body,
        headers={**auth_headers_for(A), "Idempotency-Key": "key-create-5"},
    )
    assert resp.status_code == 201, resp.text


def test_create_persists_full_set_of_rows(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    body = {
        "name": "Brunch",
        "type": "expense",
        "amount": "30.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}, {"user_id": C}],
        "payers": [{"user_id": A, "paid_amount": "30.00"}],
    }
    resp = txn_client.post(
        "/v1/transactions",
        json=body,
        headers={**auth_headers_for(A), "Idempotency-Key": "key-rows"},
    )
    assert resp.status_code == 201, resp.text
    txn_id = resp.json()["txn_id"]
    txns = txn_env["transactions_table"]
    items = txns.scan()["Items"]  # type: ignore[attr-defined]
    by_sk = {item["SK"]: item for item in items if item["PK"] == f"TXN#{txn_id}"}
    assert "META" in by_sk
    assert sum(1 for sk in by_sk if sk.startswith("MEMBER#")) == 3
    assert sum(1 for sk in by_sk if sk.startswith("AUDIT#")) == 1
    # Idempotency row.
    idemp = [
        item for item in items if str(item["PK"]).startswith("IDEMPOTENCY#")
    ]
    assert len(idemp) == 1
