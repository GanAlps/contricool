"""Tests for ``GET /v1/friends/{user_id}/balance``."""
from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

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


def test_balance_happy_returns_zero_shape(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(
        friends_env,
        user_id=REQUESTER_ID,
        email="r@example.com",
        name="R",
        currency="USD",
    )
    seed_user(friends_env, user_id=TARGET_ID, email="t@example.com", name="T")
    seed_friendship(friends_env, a_id=REQUESTER_ID, b_id=TARGET_ID)
    r = friends_client.get(
        f"/v1/friends/{TARGET_ID}/balance", headers=authed_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == TARGET_ID
    assert body["currency"] == "USD"
    assert Decimal(body["net"]) == Decimal("0")
    assert body["settlement_status"] == "settled"
    assert body["last_transaction_at"] is None


def test_balance_currency_follows_requester(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(
        friends_env,
        user_id=REQUESTER_ID,
        email="r@example.com",
        name="R",
        currency="INR",
    )
    seed_user(friends_env, user_id=TARGET_ID, email="t@example.com", name="T")
    seed_friendship(friends_env, a_id=REQUESTER_ID, b_id=TARGET_ID)
    r = friends_client.get(
        f"/v1/friends/{TARGET_ID}/balance", headers=authed_headers
    )
    assert r.status_code == 200
    assert r.json()["currency"] == "INR"


def test_balance_n21_not_a_friend(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    seed_user(friends_env, user_id=TARGET_ID, email="t@example.com", name="T")
    r = friends_client.get(
        f"/v1/friends/{TARGET_ID}/balance", headers=authed_headers
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "USER_NOT_FOUND"


def test_balance_n22_self(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    r = friends_client.get(
        f"/v1/friends/{REQUESTER_ID}/balance", headers=authed_headers
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SELF_ACTION_FORBIDDEN"


def test_balance_n23_malformed_user_id(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    r = friends_client.get(
        "/v1/friends/not-a-ulid/balance", headers=authed_headers
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_balance_unauthenticated(
    friends_client: TestClient, friends_env: dict[str, object]
) -> None:
    r = friends_client.get(f"/v1/friends/{TARGET_ID}/balance")
    assert r.status_code == 401
