"""``GET /v1/transactions`` and `?friend_id=` filter tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import auth_headers_for, seed_friendship, seed_user

A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
B = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"
C = "01HK3W7QF6VMYG8XR3DQ7B5N6R"
D = "01HK3W7QF6VMYG8XR3DQ7B5N6S"


def _seed(env: dict[str, object]) -> None:
    for uid, email in [(A, "a@x.com"), (B, "b@x.com"), (C, "c@x.com"), (D, "d@x.com")]:
        seed_user(env, user_id=uid, email=email, name=email[0].upper())
    for x, y in [(A, B), (A, C), (A, D), (B, C), (B, D)]:
        seed_friendship(env, a_id=x, b_id=y)


def _post_eq_split(
    client: TestClient,
    *,
    members: list[str],
    payer: str,
    amount: str,
    requester: str,
    key: str,
    name: str = "Item",
) -> str:
    body = {
        "name": name,
        "type": "expense",
        "amount": amount,
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": m} for m in members],
        "payers": [{"user_id": payer, "paid_amount": amount}],
    }
    resp = client.post(
        "/v1/transactions",
        json=body,
        headers={**auth_headers_for(requester, f"{requester[:1]}@x.com"), "Idempotency-Key": key},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["txn_id"]  # type: ignore[no-any-return]


def test_list_returns_only_my_txns(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed(txn_env)
    # Three transactions; A is in two, D is in one.
    _post_eq_split(
        txn_client,
        members=[A, B],
        payer=A,
        amount="10.00",
        requester=A,
        key="k1",
        name="A+B",
    )
    _post_eq_split(
        txn_client,
        members=[A, B, C],
        payer=A,
        amount="30.00",
        requester=A,
        key="k2",
        name="A+B+C",
    )
    _post_eq_split(
        txn_client,
        members=[B, D],
        payer=B,
        amount="10.00",
        requester=B,
        key="k3",
        name="B+D",
    )
    # A lists.
    resp = txn_client.get("/v1/transactions", headers=auth_headers_for(A))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert all(item["name"] in {"A+B", "A+B+C"} for item in items)


def test_list_with_friend_intersects(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed(txn_env)
    _post_eq_split(
        txn_client,
        members=[A, B],
        payer=A,
        amount="10.00",
        requester=A,
        key="kk1",
        name="A+B",
    )
    _post_eq_split(
        txn_client,
        members=[A, C],
        payer=A,
        amount="20.00",
        requester=A,
        key="kk2",
        name="A+C",
    )
    resp = txn_client.get(
        f"/v1/transactions?friend_id={B}", headers=auth_headers_for(A)
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "A+B"


def test_list_excludes_others_txns(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed(txn_env)
    _post_eq_split(
        txn_client,
        members=[B, D],
        payer=B,
        amount="10.00",
        requester=B,
        key="other1",
    )
    resp = txn_client.get("/v1/transactions", headers=auth_headers_for(A))
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_list_without_jwt_401(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    resp = txn_client.get("/v1/transactions")
    assert resp.status_code == 401


def test_list_carries_my_paid_and_owed_amounts(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Dashboard relies on per-row ``my_paid_amount`` / ``my_owed_amount``
    to compute the "you owe / you're owed" cards correctly. Three
    permutations: I paid + I'm a member; friend paid + I'm a member;
    I paid for someone else (creator on others' behalf)."""
    _seed(txn_env)
    # A paid 10, equal split with B → A is paid=10, owed=5.
    _post_eq_split(
        txn_client,
        members=[A, B],
        payer=A,
        amount="10.00",
        requester=A,
        key="paid-self",
        name="A-paid",
    )
    # B paid 30, equal split with A,B,C → from A's POV paid=0, owed=10.
    _post_eq_split(
        txn_client,
        members=[A, B, C],
        payer=B,
        amount="30.00",
        requester=B,
        key="paid-friend",
        name="B-paid",
    )

    resp = txn_client.get("/v1/transactions", headers=auth_headers_for(A))
    assert resp.status_code == 200
    items = {item["name"]: item for item in resp.json()["items"]}
    a_paid = items["A-paid"]
    assert a_paid["my_paid_amount"] == "10.00"
    assert a_paid["my_owed_amount"] == "5.00"
    b_paid = items["B-paid"]
    assert b_paid["my_paid_amount"] == "0.00"
    assert b_paid["my_owed_amount"] == "10.00"
