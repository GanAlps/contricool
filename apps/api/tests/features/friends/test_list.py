"""Tests for ``GET /v1/friends``."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core import dependencies as deps
from tests._jwt_helpers import base_id_claims, build_verifier, mint_token

from .conftest import seed_friendship, seed_user

REQUESTER_ID = "01HK3W7QF6VMYG8XR3DQ7B5N6P"


@pytest.fixture
def authed_headers() -> Iterator[dict[str, str]]:
    deps.set_verifier_for_tests(build_verifier())
    token = mint_token(
        base_id_claims(
            user_id=REQUESTER_ID, email="r@example.com", name="Requester"
        )
    )
    try:
        yield {"Authorization": f"Bearer {token}"}
    finally:
        deps.set_verifier_for_tests(None)


def _seed_pair(env: dict[str, object], idx: int) -> str:
    """Seed friend i with a deterministic, increasing user_id."""
    fid = f"01HFRIEND{idx:017d}"  # 26 chars; lexicographically ordered
    seed_user(env, user_id=fid, email=f"f{idx}@example.com", name=f"Friend{idx}")
    seed_friendship(env, a_id=REQUESTER_ID, b_id=fid)
    return fid


def test_list_empty(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    r = friends_client.get("/v1/friends", headers=authed_headers)
    assert r.status_code == 200
    body = r.json()
    assert body == {"items": [], "next_cursor": None}


def test_list_single_page(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    for i in range(3):
        _seed_pair(friends_env, i)
    r = friends_client.get("/v1/friends?limit=10", headers=authed_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    assert body["next_cursor"] is None
    # Sorted by user_id ascending.
    ids = [item["user_id"] for item in body["items"]]
    assert ids == sorted(ids)


def test_list_cursor_walk(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    for i in range(7):
        _seed_pair(friends_env, i)
    seen: list[str] = []
    cursor: str | None = None
    while True:
        url = "/v1/friends?limit=3"
        if cursor:
            url = f"{url}&cursor={cursor}"
        r = friends_client.get(url, headers=authed_headers)
        assert r.status_code == 200
        body = r.json()
        seen.extend([item["user_id"] for item in body["items"]])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 7
    assert seen == sorted(seen)
    assert len(set(seen)) == 7


def test_list_n11_limit_too_high(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    r = friends_client.get("/v1/friends?limit=101", headers=authed_headers)
    assert r.status_code == 422


def test_list_n12_limit_too_low(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    r = friends_client.get("/v1/friends?limit=0", headers=authed_headers)
    assert r.status_code == 422


def test_list_n13_tampered_cursor(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    r = friends_client.get(
        "/v1/friends?cursor=garbage", headers=authed_headers
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


def test_list_n14_cross_user_cursor(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    """Cursor minted for User B presented by User A → 422."""
    from app.features.friends.cursor import encode

    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    other_cursor = encode(
        requester_id="01J-other-user", last_friend_id="01HFRIEND00000000000000000"
    )
    r = friends_client.get(
        f"/v1/friends?cursor={other_cursor}", headers=authed_headers
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


def test_list_n15_no_email_or_phone_in_response(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    _seed_pair(friends_env, 0)
    r = friends_client.get("/v1/friends", headers=authed_headers)
    assert r.status_code == 200
    body = r.json()
    payload_str = str(body)
    assert "@" not in payload_str  # No emails anywhere.
    assert "phone" not in payload_str.lower()
    for item in body["items"]:
        assert set(item.keys()) == {"user_id", "name", "currency", "since"}


def test_list_unauthenticated(
    friends_client: TestClient, friends_env: dict[str, object]
) -> None:
    r = friends_client.get("/v1/friends")
    assert r.status_code == 401


def test_list_mixed_base_and_gsi1_sides(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
) -> None:
    """Friends both above (base) and below (GSI1) the requester's id."""
    seed_user(friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R")
    smaller = "01HAAAAA00000000000000000A"
    larger = "01HZZZZZZZZZZZZZZZZZZZZZZZ"
    seed_user(friends_env, user_id=smaller, email="s@example.com", name="Smaller")
    seed_user(friends_env, user_id=larger, email="l@example.com", name="Larger")
    seed_friendship(friends_env, a_id=REQUESTER_ID, b_id=smaller)
    seed_friendship(friends_env, a_id=REQUESTER_ID, b_id=larger)
    r = friends_client.get("/v1/friends?limit=10", headers=authed_headers)
    assert r.status_code == 200
    ids = [item["user_id"] for item in r.json()["items"]]
    assert ids == [smaller, larger]  # sorted ascending
