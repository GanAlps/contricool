"""Tests for ``POST /v1/friends/add``."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core import dependencies as deps
from app.features.friends import rate_limit as rl
from tests._jwt_helpers import base_id_claims, build_verifier, mint_token

from .conftest import seed_user

REQUESTER_ID = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
TARGET_ID = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"


@pytest.fixture
def authed_headers() -> Iterator[dict[str, str]]:
    """Authorization header carrying a valid id token for REQUESTER_ID."""
    deps.set_verifier_for_tests(build_verifier())
    token = mint_token(
        base_id_claims(
            user_id=REQUESTER_ID, email="requester@example.com", name="Requester"
        )
    )
    try:
        yield {"Authorization": f"Bearer {token}"}
    finally:
        deps.set_verifier_for_tests(None)


def test_add_friend_happy(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(
        friends_env,
        user_id=REQUESTER_ID,
        email="requester@example.com",
        name="Requester",
    )
    seed_user(
        friends_env, user_id=TARGET_ID, email="target@example.com", name="Target"
    )
    r = friends_client.post(
        "/v1/friends/add",
        json={"email": "target@example.com"},
        headers=authed_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == TARGET_ID
    assert body["name"] == "Target"
    assert body["currency"] == "USD"
    assert "since" in body


def test_add_friend_n1_phone_shaped_rejected(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    """N1: phone-shaped identifier → 422 (Pydantic EmailStr rejects)."""
    seed_user(
        friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R"
    )
    r = friends_client.post(
        "/v1/friends/add",
        json={"email": "+14155552671"},
        headers=authed_headers,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_add_friend_n2_malformed_email(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(
        friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R"
    )
    r = friends_client.post(
        "/v1/friends/add",
        json={"email": "not-an-email"},
        headers=authed_headers,
    )
    assert r.status_code == 422


def test_add_friend_n3_empty_body(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(
        friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R"
    )
    r = friends_client.post(
        "/v1/friends/add", json={}, headers=authed_headers
    )
    assert r.status_code == 422


def test_add_friend_n4_user_not_found(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(
        friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R"
    )
    r = friends_client.post(
        "/v1/friends/add",
        json={"email": "ghost@example.com"},
        headers=authed_headers,
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "USER_NOT_FOUND"


def test_add_friend_n5_conflict(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(
        friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R"
    )
    seed_user(friends_env, user_id=TARGET_ID, email="t@example.com", name="T")
    friends_client.post(
        "/v1/friends/add",
        json={"email": "t@example.com"},
        headers=authed_headers,
    )
    r = friends_client.post(
        "/v1/friends/add",
        json={"email": "t@example.com"},
        headers=authed_headers,
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"


def test_add_friend_n6_self_add(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(
        friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R"
    )
    r = friends_client.post(
        "/v1/friends/add",
        json={"email": "r@example.com"},
        headers=authed_headers,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SELF_ADD_FORBIDDEN"


def test_add_friend_n9_rate_limited(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(
        friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R"
    )
    # Pre-fill the rate-limit row to the cap.
    for _ in range(rl.HOUR_CAP):
        rl.consume_friend_add(REQUESTER_ID)
    r = friends_client.post(
        "/v1/friends/add",
        json={"email": "anyone@example.com"},
        headers=authed_headers,
    )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"
    assert "Retry-After" in r.headers


def test_add_friend_unauthenticated(
    friends_client: TestClient, friends_env: dict[str, object]
) -> None:
    """N7 prefix: any /v1/friends/* without Authorization → 401."""
    r = friends_client.post(
        "/v1/friends/add", json={"email": "t@example.com"}
    )
    assert r.status_code == 401
