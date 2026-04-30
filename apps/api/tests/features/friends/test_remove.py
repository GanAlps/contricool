"""Tests for ``DELETE /v1/friends/{user_id}``."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core import dependencies as deps
from tests._jwt_helpers import base_id_claims, build_verifier, mint_token

from .conftest import seed_friendship, seed_user

REQUESTER_ID = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
TARGET_ID = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"


@pytest.fixture
def authed_headers() -> Iterator[dict[str, str]]:
    deps.set_verifier_for_tests(build_verifier())
    token = mint_token(
        base_id_claims(user_id=REQUESTER_ID, email="r@example.com", name="R")
    )
    try:
        yield {"Authorization": f"Bearer {token}"}
    finally:
        deps.set_verifier_for_tests(None)


def test_remove_friend_happy(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    seed_user(friends_env, user_id=TARGET_ID, email="t@example.com", name="T")
    seed_friendship(friends_env, a_id=REQUESTER_ID, b_id=TARGET_ID)
    r = friends_client.delete(
        f"/v1/friends/{TARGET_ID}", headers=authed_headers
    )
    assert r.status_code == 204
    # Idempotent retry → 404.
    r = friends_client.delete(
        f"/v1/friends/{TARGET_ID}", headers=authed_headers
    )
    assert r.status_code == 404


def test_remove_friend_n17_not_a_friend(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    seed_user(friends_env, user_id=TARGET_ID, email="t@example.com", name="T")
    r = friends_client.delete(
        f"/v1/friends/{TARGET_ID}", headers=authed_headers
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "USER_NOT_FOUND"


def test_remove_friend_n18_self(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    r = friends_client.delete(
        f"/v1/friends/{REQUESTER_ID}", headers=authed_headers
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SELF_ACTION_FORBIDDEN"


def test_remove_friend_n19_malformed_user_id(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    r = friends_client.delete("/v1/friends/not-a-ulid", headers=authed_headers)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_remove_friend_unauthenticated(
    friends_client: TestClient, friends_env: dict[str, object]
) -> None:
    r = friends_client.delete(f"/v1/friends/{TARGET_ID}")
    assert r.status_code == 401


def _post_txn(
    client: TestClient,
    *,
    payer: str,
    payer_email: str,
    other: str,
    amount: str,
    idem: str,
) -> None:
    """Post a 2-member equal-split transaction via the production
    create endpoint. Caller is responsible for the verifier fixture."""
    body = {
        "name": "Dinner",
        "type": "expense",
        "amount": amount,
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": payer}, {"user_id": other}],
        "payers": [{"user_id": payer, "paid_amount": amount}],
    }
    token = mint_token(
        base_id_claims(user_id=payer, email=payer_email, name="X")
    )
    resp = client.post(
        "/v1/transactions",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": idem,
        },
    )
    assert resp.status_code == 201, resp.text


def test_remove_friend_blocked_when_balance_owed_to_requester(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    """Requester paid 20, target owes their 10 share — must settle
    before removal."""
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    seed_user(friends_env, user_id=TARGET_ID, email="t@example.com", name="T")
    seed_friendship(friends_env, a_id=REQUESTER_ID, b_id=TARGET_ID)
    _post_txn(
        friends_client,
        payer=REQUESTER_ID,
        payer_email="r@example.com",
        other=TARGET_ID,
        amount="20.00",
        idem="settle-test-1",
    )
    r = friends_client.delete(
        f"/v1/friends/{TARGET_ID}", headers=authed_headers
    )
    assert r.status_code == 409
    body = r.json()["error"]
    assert body["code"] == "BALANCE_NOT_SETTLED"
    assert body["details"][0]["field"] == "balance"


def test_remove_friend_blocked_when_requester_owes_friend(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    """Mirror case: friend paid, requester owes their share."""
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    seed_user(friends_env, user_id=TARGET_ID, email="t@example.com", name="T")
    seed_friendship(friends_env, a_id=REQUESTER_ID, b_id=TARGET_ID)
    _post_txn(
        friends_client,
        payer=TARGET_ID,
        payer_email="t@example.com",
        other=REQUESTER_ID,
        amount="20.00",
        idem="settle-test-2",
    )
    r = friends_client.delete(
        f"/v1/friends/{TARGET_ID}", headers=authed_headers
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BALANCE_NOT_SETTLED"


def test_remove_friend_unblocked_when_settled(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    """Two offsetting transactions net to zero → removal proceeds."""
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    seed_user(friends_env, user_id=TARGET_ID, email="t@example.com", name="T")
    seed_friendship(friends_env, a_id=REQUESTER_ID, b_id=TARGET_ID)
    _post_txn(
        friends_client,
        payer=REQUESTER_ID,
        payer_email="r@example.com",
        other=TARGET_ID,
        amount="20.00",
        idem="settle-test-3a",
    )
    _post_txn(
        friends_client,
        payer=TARGET_ID,
        payer_email="t@example.com",
        other=REQUESTER_ID,
        amount="20.00",
        idem="settle-test-3b",
    )

    r = friends_client.delete(
        f"/v1/friends/{TARGET_ID}", headers=authed_headers
    )
    assert r.status_code == 204
