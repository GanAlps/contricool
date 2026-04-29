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
