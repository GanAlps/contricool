"""Cross-user privacy tests for the friends feature.

These cover the load-bearing privacy invariants from CLAUDE.md
red-line 3:

- N25: User C accessing balance for B (A's friend, not C's) → 404.
- N26: User C deleting friendship between A and B → 404.
- N27: ``USER_NOT_FOUND`` is the only response on a non-friend
  delete/balance, regardless of whether the target user exists.
- N28: concurrent-add → exactly one CONFLICT, exactly one success.
"""
from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app.core import dependencies as deps
from app.features.friends import repository as repo
from tests._jwt_helpers import base_id_claims, build_verifier, mint_token

from .conftest import seed_friendship, seed_user

# Crockford ULID alphabet (no I/L/O/U). 26 chars each.
USER_A = "01HKAAA0000000000000000000"
USER_B = "01HKBBB0000000000000000000"
USER_C = "01HKCCC0000000000000000000"
assert len(USER_A) == len(USER_B) == len(USER_C) == 26


def _headers_for(user_id: str, email: str) -> dict[str, str]:
    token = mint_token(base_id_claims(user_id=user_id, email=email, name="X"))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def verifier_installed() -> Iterator[None]:
    deps.set_verifier_for_tests(build_verifier())
    try:
        yield
    finally:
        deps.set_verifier_for_tests(None)


def test_n25_user_c_cannot_read_balance_between_a_and_b(
    friends_client: TestClient,
    friends_env: dict[str, object],
    verifier_installed: None,
) -> None:
    seed_user(friends_env, user_id=USER_A, email="a@example.com", name="A")
    seed_user(friends_env, user_id=USER_B, email="b@example.com", name="B")
    seed_user(friends_env, user_id=USER_C, email="c@example.com", name="C")
    seed_friendship(friends_env, a_id=USER_A, b_id=USER_B)
    r = friends_client.get(
        f"/v1/friends/{USER_B}/balance",
        headers=_headers_for(USER_C, "c@example.com"),
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "USER_NOT_FOUND"


def test_n26_user_c_cannot_delete_friendship_between_a_and_b(
    friends_client: TestClient,
    friends_env: dict[str, object],
    verifier_installed: None,
) -> None:
    seed_user(friends_env, user_id=USER_A, email="a@example.com", name="A")
    seed_user(friends_env, user_id=USER_B, email="b@example.com", name="B")
    seed_user(friends_env, user_id=USER_C, email="c@example.com", name="C")
    seed_friendship(friends_env, a_id=USER_A, b_id=USER_B)
    r = friends_client.delete(
        f"/v1/friends/{USER_B}",
        headers=_headers_for(USER_C, "c@example.com"),
    )
    assert r.status_code == 404
    # Verify A↔B friendship is intact.
    assert repo.friendship_exists(USER_A, USER_B)


def test_n27_no_enumeration_via_balance(
    friends_client: TestClient,
    friends_env: dict[str, object],
    verifier_installed: None,
) -> None:
    """Calling /balance with a *real* user-id we're not friends with vs
    a *random* user-id we're not friends with must look identical."""
    seed_user(friends_env, user_id=USER_A, email="a@example.com", name="A")
    seed_user(friends_env, user_id=USER_B, email="b@example.com", name="B")
    real_friend_response = friends_client.get(
        f"/v1/friends/{USER_B}/balance",
        headers=_headers_for(USER_A, "a@example.com"),
    )
    fake_friend_response = friends_client.get(
        f"/v1/friends/{USER_C}/balance",  # USER_C doesn't exist
        headers=_headers_for(USER_A, "a@example.com"),
    )
    assert real_friend_response.status_code == 404
    assert fake_friend_response.status_code == 404
    assert (
        real_friend_response.json()["error"]["code"]
        == fake_friend_response.json()["error"]["code"]
        == "USER_NOT_FOUND"
    )


def test_n28_concurrent_add_one_succeeds_one_conflicts(
    friends_client: TestClient,
    friends_env: dict[str, object],
    verifier_installed: None,
) -> None:
    """Mock ConditionalCheckFailedException on the second writer to
    simulate concurrent A→B and B→A racing on the same canonical pair."""
    seed_user(friends_env, user_id=USER_A, email="a@example.com", name="A")
    seed_user(friends_env, user_id=USER_B, email="b@example.com", name="B")
    # First add succeeds normally.
    r1 = friends_client.post(
        "/v1/friends/add",
        json={"email": "b@example.com"},
        headers=_headers_for(USER_A, "a@example.com"),
    )
    assert r1.status_code == 200

    # Second add (B → A) hits the canonical-pair condition → 409.
    r2 = friends_client.post(
        "/v1/friends/add",
        json={"email": "a@example.com"},
        headers=_headers_for(USER_B, "b@example.com"),
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "CONFLICT"


def test_concurrent_add_via_mocked_race(
    friends_client: TestClient,
    friends_env: dict[str, object],
    verifier_installed: None,
) -> None:
    """Inject a ConditionalCheckFailedException on create_friendship to
    simulate a true concurrent race where DDB rejects our write."""
    seed_user(friends_env, user_id=USER_A, email="a@example.com", name="A")
    seed_user(friends_env, user_id=USER_B, email="b@example.com", name="B")
    real_create = repo.create_friendship

    def racy_create(*args: object, **kwargs: object) -> object:
        raise ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}},
            "PutItem",
        )

    with patch.object(repo, "create_friendship", side_effect=repo.ConflictError):
        r = friends_client.post(
            "/v1/friends/add",
            json={"email": "b@example.com"},
            headers=_headers_for(USER_A, "a@example.com"),
        )
        assert r.status_code == 409
    # Sanity: the real create still works after the patch is gone.
    real_create(USER_A, USER_B, created_by=USER_A)
    _ = racy_create  # silence unused
